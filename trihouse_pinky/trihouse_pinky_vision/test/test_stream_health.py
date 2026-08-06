from trihouse_pinky_vision.process_metrics import ProgressSample
from trihouse_pinky_vision.stream_health import StreamHealthStateMachine, StreamState


def sample(frame_count: int) -> ProgressSample:
    return ProgressSample(frame_count=frame_count, reported_fps=15.0, out_time_seconds=0.0)


def test_becomes_healthy_only_after_five_seconds_of_good_progress():
    monitor = StreamHealthStateMachine(target_fps=15.0)

    states = [monitor.update(sample(1 + 15 * second), True, float(second)).state
              for second in range(6)]

    assert states[:5] == [StreamState.RECOVERING] * 5
    assert states[5] == StreamState.HEALTHY
    assert monitor.snapshot.fps == 15.0


def test_degrades_after_one_second_without_new_frame():
    monitor = StreamHealthStateMachine(target_fps=15.0)
    monitor.update(sample(1), True, 0.0)

    result = monitor.update(None, True, 1.0)

    assert result.state == StreamState.DEGRADED
    assert result.reason == 'no_progress'


def test_disconnects_after_three_seconds_without_new_frame():
    monitor = StreamHealthStateMachine(target_fps=15.0)
    monitor.update(sample(1), True, 0.0)

    result = monitor.update(None, True, 3.0)

    assert result.state == StreamState.DISCONNECTED
    assert result.reason == 'no_progress_timeout'


def test_disconnects_immediately_when_a_child_exits():
    monitor = StreamHealthStateMachine(target_fps=15.0)

    result = monitor.update(None, False, 0.0)

    assert result.state == StreamState.DISCONNECTED
    assert result.reason == 'publisher_exit'


def test_repeated_frame_count_is_not_fresh_progress():
    monitor = StreamHealthStateMachine(target_fps=15.0)
    monitor.update(sample(20), True, 0.0)

    result = monitor.update(sample(20), True, 1.0)

    assert result.state == StreamState.DEGRADED
    assert result.last_frame_monotonic == 0.0


def test_recovery_requires_a_new_five_second_healthy_window():
    monitor = StreamHealthStateMachine(target_fps=15.0)
    monitor.update(sample(1), True, 0.0)
    monitor.update(None, True, 3.0)

    recovering = monitor.update(sample(61), True, 4.0)
    not_yet_healthy = monitor.update(sample(121), True, 8.0)
    healthy = monitor.update(sample(136), True, 9.0)

    assert recovering.state == StreamState.RECOVERING
    assert not_yet_healthy.state == StreamState.RECOVERING
    assert healthy.state == StreamState.HEALTHY


def test_accepts_reset_frame_counter_after_publisher_restart():
    monitor = StreamHealthStateMachine(target_fps=15.0)
    monitor.update(sample(100), True, 0.0)
    monitor.update(None, False, 1.0)

    recovering = monitor.update(sample(1), True, 2.0)

    assert recovering.state == StreamState.RECOVERING
    assert recovering.reason == 'frames_resumed'
    assert recovering.fps == 15.0
    assert recovering.last_frame_monotonic == 2.0


def test_repeated_frame_count_stays_disconnected_after_timeout():
    monitor = StreamHealthStateMachine(target_fps=15.0)
    monitor.update(sample(100), True, 0.0)
    disconnected = monitor.update(sample(100), True, 3.0)

    still_disconnected = monitor.update(sample(100), True, 4.0)

    assert disconnected.state == StreamState.DISCONNECTED
    assert still_disconnected.state == StreamState.DISCONNECTED
    assert still_disconnected.reason == 'no_progress_timeout'
    assert still_disconnected.last_frame_monotonic == 0.0


def test_reports_recovering_while_restart_cleanup_runs():
    monitor = StreamHealthStateMachine(target_fps=15.0)
    monitor.update(sample(100), True, 0.0)
    monitor.update(None, False, 1.0)

    restarting = monitor.restarting(2.0)

    assert restarting.state == StreamState.RECOVERING
    assert restarting.reason == 'restart_in_progress'
    assert restarting.fps == 0.0
    assert restarting.last_frame_monotonic is None

    resumed = monitor.update(sample(1), True, 3.0)

    assert resumed.state == StreamState.RECOVERING
    assert resumed.last_frame_monotonic == 3.0
