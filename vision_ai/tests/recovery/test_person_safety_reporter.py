"""The 5080 person reporter must not credit unobserved time as recovery."""

from contextlib import contextmanager

import numpy as np
import pytest

from vision_ai.robot.recovery import live_runtime
from vision_ai.robot.recovery.live_runtime import PersonSafetyReporter
from vision_ai.robot.perception.fall_monitor import FallState


SHAPE = (120, 160, 3)


@pytest.fixture
def reporter(monkeypatch):
    @contextmanager
    def fake_urlopen(*args, **kwargs):
        class Response:
            def read(self):
                return b"{}"

        yield Response()

    monkeypatch.setattr(live_runtime.request, "urlopen", fake_urlopen)
    return PersonSafetyReporter("http://gateway", "CAM-01")


class TrackedDetection:
    """A person detection carrying a cross-frame identity."""

    class_id = 1

    def __init__(self, track_id: str, *, width: int, height: int, x: int = 10,
                 confidence: float = 0.9):
        self.track_id = track_id
        self.confidence = confidence
        self.mask = np.zeros((120, 160), dtype=bool)
        self.mask[10:10 + height, x:x + width] = True


def lying(track_id: str, **kwargs) -> TrackedDetection:
    return TrackedDetection(track_id, width=90, height=30, **kwargs)


def upright(track_id: str, **kwargs) -> TrackedDetection:
    return TrackedDetection(track_id, width=20, height=90, **kwargs)


def test_a_walking_bystander_does_not_erase_a_fallen_person(reporter) -> None:
    """The reporter used to take one person per frame and share one monitor."""
    for step, bystander_x in enumerate([60, 80, 100, 60, 80, 100, 60, 80]):
        reporter.observe_frame(
            [lying("a"), upright("b", x=bystander_x, confidence=0.95)],
            SHAPE, float(step),
        )

    assert reporter.last_state == FallState.EMERGENCY_CANDIDATE.value


def test_the_reporter_reaches_fallen_from_a_lying_mask(reporter) -> None:
    """Guards the fixtures themselves: the states below have to be reachable."""
    reporter.observe_frame([lying("a")], SHAPE, 0.0)
    reporter.observe_frame([lying("a")], SHAPE, 1.5)

    assert reporter.last_state == FallState.FALLEN.value


def test_time_off_camera_does_not_clear_a_fall(reporter) -> None:
    reporter.observe_frame([lying("a")], SHAPE, 0.0)
    reporter.observe_frame([lying("a")], SHAPE, 1.5)
    # One upright reading opens the recovery candidate, then they leave frame.
    reporter.observe_frame([upright("a")], SHAPE, 2.0)
    assert reporter.last_state == FallState.FALLEN.value

    for now in (2.5, 3.0, 3.5):
        reporter.observe_frame([], SHAPE, now)

    # Returning upright after the gap must not clear the fall on the first frame.
    reporter.observe_frame([upright("a")], SHAPE, 6.0)
    assert reporter.last_state == FallState.FALLEN.value
    # A full observed recovery_confirm_seconds is what clears it.
    reporter.observe_frame([upright("a")], SHAPE, 7.5)
    assert reporter.last_state == FallState.NORMAL.value
