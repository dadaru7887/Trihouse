import json
from pathlib import Path

from model.worker.person.fall_monitor import FallMonitor, FallState, MonitorConfig


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


def test_oscillating_micro_motion_still_reaches_the_emergency_threshold() -> None:
    """A person breathing on the floor flips FALLEN<->IMMOBILE every frame.

    Measuring immobile_seconds from the latest transition restarts the clock on
    every flip, so a genuinely motionless person is never escalated. The stillness
    clock must survive the flips and only reset on a real recovery.
    """
    monitor = FallMonitor(MonitorConfig(fall_confirm_seconds=1, immobile_seconds=5))
    monitor.advance(0, fallen=True, low_motion=True)   # FALL_SUSPECTED
    monitor.advance(1, fallen=True, low_motion=True)   # FALLEN

    states = []
    for step in range(2, 16):
        # Mostly still, with a twitch every third frame. IMMOBILE is held across
        # consecutive frames — so the escalation check is genuinely reached — but
        # each twitch drops back to FALLEN and restarts `since`.
        states.append(monitor.advance(step, fallen=True, low_motion=step % 3 != 0)["state"])

    assert FallState.EMERGENCY_CANDIDATE.value in states


def test_time_a_person_was_off_camera_is_not_counted_as_recovery() -> None:
    """Wall-clock time with no observation is not evidence that they got up."""
    monitor = FallMonitor(MonitorConfig(fall_confirm_seconds=1, immobile_seconds=5,
                                        recovery_confirm_seconds=1))
    monitor.advance(0, fallen=True, low_motion=True)   # FALL_SUSPECTED
    monitor.advance(1, fallen=True, low_motion=True)   # FALLEN
    monitor.advance(2, fallen=False, low_motion=True)  # recovery candidate opens

    for _ in range(3):
        monitor.note_no_detection()                    # person walks out of frame

    # First frame after they reappear: the unobserved gap must not count.
    assert monitor.advance(6, fallen=False, low_motion=True)["state"] == FallState.FALLEN.value
    # One observed second of "not fallen" is what actually clears it.
    assert monitor.advance(7, fallen=False, low_motion=True)["state"] == FallState.NORMAL.value


def test_the_escalation_clock_measures_stillness_not_time_since_falling() -> None:
    """Deliberate choice: immobile_seconds keeps meaning "how long they lay still".

    A person who falls and thrashes for several seconds has not yet been still,
    so the escalation clock starts when stillness starts, not when they fell.
    """
    monitor = FallMonitor(MonitorConfig(fall_confirm_seconds=1, immobile_seconds=5))
    monitor.advance(0, fallen=True, low_motion=False)    # FALL_SUSPECTED
    monitor.advance(1, fallen=True, low_motion=False)    # FALLEN, still moving
    for step in (2, 3, 4, 5, 6):
        monitor.advance(step, fallen=True, low_motion=False)  # thrashing, stays FALLEN

    monitor.advance(7, fallen=True, low_motion=True)     # stillness begins here
    assert monitor.advance(11.9, fallen=True, low_motion=True)["state"] == FallState.IMMOBILE.value
    assert monitor.advance(12, fallen=True, low_motion=True)["state"] == FallState.EMERGENCY_CANDIDATE.value
