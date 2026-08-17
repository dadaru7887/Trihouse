from trihouse_pinky_vision.process_metrics import ProgressSample
from trihouse_pinky_vision.stream_health import StreamHealthStateMachine, StreamState


def sample(frame_count: int, out_time: float = 0.0) -> ProgressSample:
    return ProgressSample(
        frame_count=frame_count,
        reported_fps=15.0,
        out_time_seconds=out_time,
    )


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


def test_monotonic_timestamps_are_not_reported_as_a_regression():
    monitor = StreamHealthStateMachine(target_fps=15.0)

    first = monitor.update(sample(15, out_time=1.0), True, 1.0)
    second = monitor.update(sample(30, out_time=2.0), True, 2.0)

    assert not first.timestamp_regressed
    assert not second.timestamp_regressed


def test_regressing_timestamp_is_reported_without_changing_the_state():
    """타임스탬프 단조성은 완료 기준인데 여태 손으로만 확인했다.

    `out_time_seconds` 는 이미 파싱되어 흐르고 있으므로, 상태 전이는 건드리지
    않고 관측만 붙인다. 되돌아간 타임스탬프는 상태를 바꿀 만큼 확실한 고장이
    아니라 조사할 단서다.
    """
    monitor = StreamHealthStateMachine(target_fps=15.0)
    for second in range(6):
        healthy = monitor.update(
            sample(1 + 15 * second, out_time=float(second)), True, float(second)
        )

    assert healthy.state == StreamState.HEALTHY
    assert not healthy.timestamp_regressed

    regressed = monitor.update(sample(91, out_time=2.0), True, 6.0)

    assert regressed.timestamp_regressed
    # 상태 기계의 기존 전이는 그대로다.
    assert regressed.state == StreamState.HEALTHY


def test_regression_is_reported_only_for_the_sample_that_went_backwards():
    monitor = StreamHealthStateMachine(target_fps=15.0)
    monitor.update(sample(15, out_time=5.0), True, 1.0)
    monitor.update(sample(30, out_time=2.0), True, 2.0)

    resumed = monitor.update(sample(45, out_time=3.0), True, 3.0)

    assert not resumed.timestamp_regressed


def test_restart_induced_timestamp_reset_is_not_a_regression():
    # 재시작하면 FFmpeg 가 0 부터 다시 센다. 그것은 고장이 아니라 정상이다.
    monitor = StreamHealthStateMachine(target_fps=15.0)
    monitor.update(sample(100, out_time=40.0), True, 0.0)

    monitor.restarting(1.0)
    resumed = monitor.update(sample(1, out_time=0.1), True, 2.0)

    assert not resumed.timestamp_regressed


def test_publisher_exit_and_resume_does_not_report_a_regression():
    # 프로세스가 죽었다 살아나도 카운터가 0 부터 다시 시작한다.
    monitor = StreamHealthStateMachine(target_fps=15.0)
    monitor.update(sample(100, out_time=40.0), True, 0.0)
    monitor.update(None, False, 1.0)

    resumed = monitor.update(sample(1, out_time=0.1), True, 2.0)

    assert resumed.reason == 'frames_resumed'
    assert not resumed.timestamp_regressed


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
