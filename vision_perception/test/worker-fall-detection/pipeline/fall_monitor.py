from dataclasses import dataclass
from enum import Enum
from math import hypot


class FallState(str, Enum):
    NORMAL = "NORMAL"
    FALL_SUSPECTED = "FALL_SUSPECTED"
    FALLEN = "FALLEN"
    IMMOBILE = "IMMOBILE"
    EMERGENCY_CANDIDATE = "EMERGENCY_CANDIDATE"


@dataclass(frozen=True)
class MonitorConfig:
    fall_aspect_ratio: float = 1.2
    fall_confirm_seconds: float = 1.0
    immobile_seconds: float = 5.0
    motion_threshold: float = 0.015


class FallMonitor:
    def __init__(self, config: MonitorConfig) -> None:
        self.config = config
        self.state = FallState.NORMAL
        self.since = 0.0
        self.last_centroid: tuple[float, float] | None = None
        self.event_sent = False

    def update(self, timestamp: float, aspect_ratio: float, centroid: tuple[float, float], frame_diagonal: float) -> dict:
        motion = 0.0 if self.last_centroid is None else hypot(centroid[0] - self.last_centroid[0], centroid[1] - self.last_centroid[1]) / max(frame_diagonal, 1.0)
        self.last_centroid = centroid
        fallen = aspect_ratio >= self.config.fall_aspect_ratio
        low_motion = motion <= self.config.motion_threshold
        previous = self.state
        if not fallen:
            self.state, self.since, self.event_sent = FallState.NORMAL, timestamp, False
        elif self.state == FallState.NORMAL:
            self.state, self.since = FallState.FALL_SUSPECTED, timestamp
        elif self.state == FallState.FALL_SUSPECTED and timestamp - self.since >= self.config.fall_confirm_seconds:
            self.state, self.since = FallState.FALLEN, timestamp
        elif self.state == FallState.FALLEN and low_motion:
            self.state, self.since = FallState.IMMOBILE, timestamp
        elif self.state == FallState.IMMOBILE and not low_motion:
            self.state, self.since = FallState.FALLEN, timestamp
        elif self.state == FallState.IMMOBILE and timestamp - self.since >= self.config.immobile_seconds:
            self.state = FallState.EMERGENCY_CANDIDATE
        event = self.state == FallState.EMERGENCY_CANDIDATE and not self.event_sent
        if event:
            self.event_sent = True
        return {"state": self.state.value, "previous_state": previous.value, "motion": motion, "event": event}


def mask_geometry(mask) -> tuple[float, tuple[float, float]] | None:
    import numpy as np
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    width, height = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
    return width / max(height, 1), (float(xs.mean()), float(ys.mean()))
