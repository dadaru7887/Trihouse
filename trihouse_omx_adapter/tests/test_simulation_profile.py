from __future__ import annotations

import pytest

from trihouse_omx_adapter.simulation_profile import (
    PhaseSample,
    sample_phase,
    validate_feedback,
)


@pytest.mark.parametrize(
    ("elapsed_s", "expected_phase", "expected_phase_elapsed_s", "expected_progress"),
    (
        (0.0, "picking", 0.0, 0.0),
        (7.499, "picking", 7.499, pytest.approx(49.993, abs=0.001)),
        (7.5, "loading", 0.0, 50.0),
        (14.999, "loading", 7.499, pytest.approx(99.993, abs=0.001)),
        (15.0, "succeeded", 7.5, 100.0),
    ),
)
def test_phase_boundaries_preserve_the_fifteen_second_transfer(
    elapsed_s: float,
    expected_phase: str,
    expected_phase_elapsed_s: float,
    expected_progress: float,
) -> None:
    """Catches early success or a picking/loading boundary at the wrong time."""

    sample = sample_phase(elapsed_s)

    assert sample.phase.value == expected_phase
    assert sample.phase_elapsed_s == pytest.approx(expected_phase_elapsed_s, abs=1e-9)
    assert sample.total_elapsed_s == elapsed_s
    assert sample.progress == expected_progress


def test_negative_elapsed_time_is_rejected() -> None:
    """Catches accepting a clock jump before the transfer start."""

    with pytest.raises(ValueError, match="elapsed_s must be non-negative"):
        sample_phase(-0.001)


def test_feedback_rejects_phase_regression() -> None:
    """Catches a loading heartbeat that later reports picking again."""

    previous = PhaseSample.from_values("loading", 1.0, 8.5, 56.667)
    current = PhaseSample.from_values("picking", 6.0, 9.0, 60.0)

    with pytest.raises(ValueError, match="phase regression"):
        validate_feedback(previous, current)


def test_feedback_rejects_progress_regression() -> None:
    """Catches monotonic phase with a decreasing overall progress value."""

    previous = PhaseSample.from_values("picking", 6.0, 6.0, 40.0)
    current = PhaseSample.from_values("picking", 6.5, 6.5, 39.0)

    with pytest.raises(ValueError, match="progress regression"):
        validate_feedback(previous, current)


def test_feedback_rejects_terminal_success_before_fifteen_seconds() -> None:
    """Catches an OMX result that claims success before loading is complete."""

    early = PhaseSample.from_values("succeeded", 7.5, 14.9, 100.0)

    with pytest.raises(ValueError, match="terminal feedback before 15 seconds"):
        validate_feedback(None, early)
