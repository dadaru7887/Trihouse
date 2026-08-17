"""Pure stream-health state machine with no ROS dependency."""

from dataclasses import dataclass
from enum import IntEnum

from .process_metrics import ProgressSample


class StreamState(IntEnum):
    UNKNOWN = 0
    HEALTHY = 1
    DEGRADED = 2
    DISCONNECTED = 3
    RECOVERING = 4


@dataclass(frozen=True)
class HealthSnapshot:
    state: StreamState
    fps: float
    bitrate_kbps: float
    last_frame_monotonic: float | None
    reason: str
    # 직전 표본보다 `out_time_seconds` 가 뒤로 갔는가. 상태를 바꾸지 않고
    # 관측만 싣는다. 자세한 이유는 아래 `_note_timestamp` 참고.
    timestamp_regressed: bool = False


class StreamHealthStateMachine:
    def __init__(
        self,
        target_fps: float,
        degraded_after_sec: float = 1.0,
        disconnected_after_sec: float = 3.0,
        healthy_after_sec: float = 5.0,
    ) -> None:
        self._target_fps = target_fps
        self._degraded_after = degraded_after_sec
        self._disconnected_after = disconnected_after_sec
        self._healthy_after = healthy_after_sec
        self._started_at: float | None = None
        self._last_frame_count: int | None = None
        self._last_frame_time: float | None = None
        self._last_out_time: float | None = None
        self._healthy_since: float | None = None
        self._below_healthy_since: float | None = None
        self._snapshot = HealthSnapshot(StreamState.RECOVERING, 0.0, 0.0, None, 'starting')

    @property
    def snapshot(self) -> HealthSnapshot:
        return self._snapshot

    def restarting(self, now: float, bitrate_kbps: float = 0.0) -> HealthSnapshot:
        """Report recovery while process cleanup and replacement run."""
        self._started_at = now
        self._last_frame_count = None
        self._last_frame_time = None
        # 재시작하면 FFmpeg 가 0 부터 다시 센다. 기준을 지우지 않으면 그 정상
        # 동작이 곧바로 역행으로 보고된다.
        self._last_out_time = None
        self._healthy_since = None
        self._below_healthy_since = None
        return self._set(
            StreamState.RECOVERING,
            bitrate_kbps,
            'restart_in_progress',
            fps=0.0,
        )

    def update(
        self,
        sample: ProgressSample | None,
        processes_alive: bool,
        now: float,
        bitrate_kbps: float = 0.0,
    ) -> HealthSnapshot:
        if self._started_at is None:
            self._started_at = now
        if not processes_alive:
            self._healthy_since = None
            return self._set(StreamState.DISCONNECTED, bitrate_kbps, 'publisher_exit')

        is_new = sample is not None and (
            self._last_frame_count is None
            or sample.frame_count > self._last_frame_count
            or (
                self._snapshot.state == StreamState.DISCONNECTED
                and sample.frame_count < self._last_frame_count
            )
        )
        if is_new and sample is not None:
            return self._on_progress(sample, now, bitrate_kbps)
        return self._on_silence(now, bitrate_kbps)

    def _on_progress(
        self,
        sample: ProgressSample,
        now: float,
        bitrate_kbps: float,
    ) -> HealthSnapshot:
        was_disconnected = self._snapshot.state == StreamState.DISCONNECTED
        if was_disconnected or self._last_frame_count is None or self._last_frame_time is None:
            fps = max(0.0, sample.reported_fps)
        else:
            elapsed = now - self._last_frame_time
            fps = ((sample.frame_count - self._last_frame_count) / elapsed) if elapsed > 0 else 0.0

        regressed = self._note_timestamp(sample.out_time_seconds, was_disconnected)
        self._last_frame_count = sample.frame_count
        self._last_frame_time = now
        healthy_threshold = self._target_fps * 0.9
        degraded_threshold = self._target_fps * 0.5

        if was_disconnected:
            self._healthy_since = now if fps >= healthy_threshold else None
            self._below_healthy_since = None
            return self._set(
                StreamState.RECOVERING, bitrate_kbps, 'frames_resumed', fps, regressed
            )

        if fps >= healthy_threshold:
            self._below_healthy_since = None
            if self._healthy_since is None:
                self._healthy_since = now
            if now - self._healthy_since >= self._healthy_after:
                return self._set(StreamState.HEALTHY, bitrate_kbps, 'healthy', fps, regressed)
            return self._set(StreamState.RECOVERING, bitrate_kbps, 'healthy_gate', fps, regressed)

        self._healthy_since = None
        if fps < degraded_threshold:
            self._below_healthy_since = now
            return self._set(StreamState.DEGRADED, bitrate_kbps, 'low_fps', fps, regressed)
        if self._below_healthy_since is None:
            self._below_healthy_since = now
        if now - self._below_healthy_since >= 10.0:
            return self._set(
                StreamState.DEGRADED, bitrate_kbps, 'below_target_fps', fps, regressed
            )
        return self._set(
            StreamState.RECOVERING, bitrate_kbps, 'below_healthy_threshold', fps, regressed
        )

    def _note_timestamp(self, out_time_seconds: float, was_disconnected: bool) -> bool:
        """`out_time_seconds` 가 뒤로 갔는지 보고 기준값을 갱신한다.

        단조 증가는 명시된 완료 기준인데 여태 `verify_rtsp.sh` 로 손으로만
        확인했다. 필요한 값은 이미 `ProgressSample.out_time_seconds` 로 파싱되어
        흐르고 있었고 테스트 밖에서 아무도 쓰지 않았으므로, 상태 전이는 그대로
        두고 관측만 붙인다.

        상태를 바꾸지 않는 이유는 역행이 그 자체로 확실한 고장이 아니기
        때문이다. 재시작이나 발행자 교체 뒤에는 정상적으로 0 부터 다시 세므로,
        그런 재설정은 역행으로 세지 않는다. 남는 역행은 조사할 단서이지
        재시작을 정당화하는 근거가 아니다.
        """
        previous = self._last_out_time
        self._last_out_time = out_time_seconds
        if was_disconnected or previous is None:
            # 끊겼다 재개된 흐름은 새 기준으로 시작한다.
            return False
        return out_time_seconds < previous

    def _on_silence(self, now: float, bitrate_kbps: float) -> HealthSnapshot:
        reference = (
            self._last_frame_time
            if self._last_frame_time is not None
            else self._started_at
        )
        silence = now - reference if reference is not None else 0.0
        self._healthy_since = None
        if silence >= self._disconnected_after:
            return self._set(StreamState.DISCONNECTED, bitrate_kbps, 'no_progress_timeout')
        if silence >= self._degraded_after:
            return self._set(StreamState.DEGRADED, bitrate_kbps, 'no_progress')
        return self._set(StreamState.RECOVERING, bitrate_kbps, 'waiting_for_frame')

    def _set(
        self,
        state: StreamState,
        bitrate_kbps: float,
        reason: str,
        fps: float | None = None,
        timestamp_regressed: bool = False,
    ) -> HealthSnapshot:
        self._snapshot = HealthSnapshot(
            state=state,
            fps=self._snapshot.fps if fps is None else fps,
            bitrate_kbps=bitrate_kbps,
            last_frame_monotonic=self._last_frame_time,
            reason=reason,
            # 사건이므로 들고 있지 않는다. 역행이 관측된 표본에서만 참이다.
            timestamp_regressed=timestamp_regressed,
        )
        return self._snapshot
