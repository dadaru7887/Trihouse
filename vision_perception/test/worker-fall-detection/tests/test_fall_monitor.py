import json
from pathlib import Path

from pipeline.fall_monitor import FallMonitor, FallState, MonitorConfig


def test_fall_and_immobility_emits_one_candidate_event() -> None:
    monitor = FallMonitor(MonitorConfig(fall_confirm_seconds=1, immobile_seconds=2))
    assert monitor.update(0, 1.3, (10, 10), 100)["state"] == FallState.FALL_SUSPECTED.value
    assert monitor.update(1, 1.3, (10, 10), 100)["state"] == FallState.FALLEN.value
    assert monitor.update(2, 1.3, (10, 10), 100)["state"] == FallState.IMMOBILE.value
    result = monitor.update(4, 1.3, (10, 10), 100)
    assert result["state"] == FallState.EMERGENCY_CANDIDATE.value
    assert result["event"] is True
    assert monitor.update(5, 1.3, (10, 10), 100)["event"] is False


def test_recovery_resets_state() -> None:
    monitor = FallMonitor(MonitorConfig())
    monitor.update(0, 1.3, (0, 0), 100)
    assert monitor.update(1, 0.5, (0, 0), 100)["state"] == FallState.NORMAL.value
