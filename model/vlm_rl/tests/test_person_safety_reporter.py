"""The 5080 person reporter must not credit unobserved time as recovery."""

from contextlib import contextmanager

import numpy as np
import pytest

from model.vlm_rl.inference import live_runtime
from model.vlm_rl.inference.live_runtime import PersonSafetyReporter
from model.worker.person.fall_monitor import FallState


class FakeDetection:
    confidence = 0.9

    def __init__(self, width: int, height: int):
        self.mask = np.zeros((120, 160), dtype=bool)
        self.mask[10:10 + height, 10:10 + width] = True


LYING = FakeDetection(width=90, height=30)     # aspect ratio 3.0 -> fallen
STANDING = FakeDetection(width=20, height=90)  # aspect ratio 0.22 -> not fallen
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


def test_the_reporter_reaches_fallen_from_a_lying_mask(reporter) -> None:
    """Guards the fixture itself: the states below have to be reachable."""
    reporter.observe(LYING, SHAPE, 0.0)
    reporter.observe(LYING, SHAPE, 1.5)

    assert reporter.monitor.state is FallState.FALLEN


def test_time_off_camera_does_not_clear_a_fall(reporter) -> None:
    reporter.observe(LYING, SHAPE, 0.0)
    reporter.observe(LYING, SHAPE, 1.5)
    # One upright reading opens the recovery candidate, then they leave frame.
    reporter.observe(STANDING, SHAPE, 2.0)
    assert reporter.monitor.recovery_since == 2.0

    for now in (3.0, 4.0, 5.0):
        reporter.observe(None, SHAPE, now)

    assert reporter.monitor.recovery_since is None
    # Returning upright after the gap must not clear the fall on the first frame.
    reporter.observe(STANDING, SHAPE, 6.0)
    assert reporter.monitor.state is FallState.FALLEN
    # A full observed recovery_confirm_seconds is what clears it.
    reporter.observe(STANDING, SHAPE, 7.5)
    assert reporter.monitor.state is FallState.NORMAL
