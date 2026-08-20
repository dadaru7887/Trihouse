import json
from pathlib import Path

from vision_system.person_worker.fall_monitor import FallMonitor, FallState, MonitorConfig


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


def test_single_noisy_frame_does_not_erase_immobile_progress() -> None:
    monitor = FallMonitor(MonitorConfig(fall_confirm_seconds=1, immobile_seconds=2, recovery_confirm_seconds=1))
    monitor.update(0, 1.3, (10, 10), 100)  # FALL_SUSPECTED
    monitor.update(1, 1.3, (10, 10), 100)  # FALLEN
    assert monitor.update(2, 1.3, (10, 10), 100)["state"] == FallState.IMMOBILE.value
    # One noisy low-ratio frame right before the emergency threshold should not
    # wipe out the accumulated IMMOBILE evidence.
    noisy = monitor.update(3, 0.5, (10, 10), 100)
    assert noisy["state"] == FallState.IMMOBILE.value
    # Real fallen readings resume and the emergency alert still fires.
    result = monitor.update(4, 1.3, (10, 10), 100)
    assert result["state"] == FallState.EMERGENCY_CANDIDATE.value
    assert result["event"] is True


def test_sustained_recovery_still_resets_from_immobile() -> None:
    monitor = FallMonitor(MonitorConfig(fall_confirm_seconds=1, immobile_seconds=2, recovery_confirm_seconds=1))
    monitor.update(0, 1.3, (10, 10), 100)  # FALL_SUSPECTED
    monitor.update(1, 1.3, (10, 10), 100)  # FALLEN
    monitor.update(2, 1.3, (10, 10), 100)  # IMMOBILE
    monitor.update(3, 0.5, (10, 10), 100)  # recovery candidate starts
    result = monitor.update(4.5, 0.5, (10, 10), 100)  # 1.5s of sustained "not fallen"
    assert result["state"] == FallState.NORMAL.value
