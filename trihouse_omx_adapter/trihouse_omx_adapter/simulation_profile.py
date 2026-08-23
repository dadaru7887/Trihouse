"""Deterministic timing and feedback rules for the simulated OMX transfer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


PICKING_DURATION_S = 7.5
LOADING_DURATION_S = 7.5
TRANSFER_DURATION_S = PICKING_DURATION_S + LOADING_DURATION_S


class OmxPhase(str, Enum):
    PICKING = "picking"
    LOADING = "loading"
    SUCCEEDED = "succeeded"


_PHASE_ORDER = {
    OmxPhase.PICKING: 0,
    OmxPhase.LOADING: 1,
    OmxPhase.SUCCEEDED: 2,
}


@dataclass(frozen=True)
class PhaseSample:
    phase: OmxPhase
    phase_elapsed_s: float
    total_elapsed_s: float
    progress: float

    def __post_init__(self) -> None:
        values = (self.phase_elapsed_s, self.total_elapsed_s, self.progress)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("feedback values must be finite")
        if self.phase_elapsed_s < 0 or self.total_elapsed_s < 0:
            raise ValueError("feedback time must be non-negative")
        if not 0.0 <= self.progress <= 100.0:
            raise ValueError("progress must be between 0 and 100")

    @classmethod
    def from_values(
        cls,
        phase: str,
        phase_elapsed_s: float,
        total_elapsed_s: float,
        progress: float,
    ) -> "PhaseSample":
        return cls(
            OmxPhase(phase),
            float(phase_elapsed_s),
            float(total_elapsed_s),
            float(progress),
        )


def sample_phase(elapsed_s: float) -> PhaseSample:
    """Return the transfer phase at an elapsed ROS simulation time."""

    if not math.isfinite(elapsed_s):
        raise ValueError("elapsed_s must be finite")
    if elapsed_s < 0:
        raise ValueError("elapsed_s must be non-negative")
    if elapsed_s < PICKING_DURATION_S:
        return PhaseSample(
            OmxPhase.PICKING,
            elapsed_s,
            elapsed_s,
            elapsed_s / TRANSFER_DURATION_S * 100.0,
        )
    if elapsed_s < TRANSFER_DURATION_S:
        return PhaseSample(
            OmxPhase.LOADING,
            elapsed_s - PICKING_DURATION_S,
            elapsed_s,
            elapsed_s / TRANSFER_DURATION_S * 100.0,
        )
    return PhaseSample(
        OmxPhase.SUCCEEDED,
        LOADING_DURATION_S,
        elapsed_s,
        100.0,
    )


def validate_feedback(
    previous: PhaseSample | None,
    current: PhaseSample,
) -> None:
    """Reject feedback that cannot belong to one forward OMX execution."""

    if current.phase is OmxPhase.SUCCEEDED and current.total_elapsed_s < TRANSFER_DURATION_S:
        raise ValueError("terminal feedback before 15 seconds")
    if previous is None:
        return
    if _PHASE_ORDER[current.phase] < _PHASE_ORDER[previous.phase]:
        raise ValueError("phase regression")
    if current.total_elapsed_s < previous.total_elapsed_s:
        raise ValueError("elapsed time regression")
    if current.progress < previous.progress:
        raise ValueError("progress regression")


__all__ = [
    "LOADING_DURATION_S",
    "OmxPhase",
    "PICKING_DURATION_S",
    "PhaseSample",
    "TRANSFER_DURATION_S",
    "sample_phase",
    "validate_feedback",
]
