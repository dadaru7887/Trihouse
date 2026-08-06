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
        self._healthy_since: float | None = None
        self._below_healthy_since: float | None = None
        self._snapshot = HealthSnapshot(StreamState.RECOVERING, 0.0, 0.0, None, 'starting')

    @property
    def snapshot(self) -> HealthSnapshot:
        return self._snapshot

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
            self._snapshot.state == StreamState.DISCONNECTED
            or self._last_frame_count is None
            or sample.frame_count > self._last_frame_count
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

        self._last_frame_count = sample.frame_count
        self._last_frame_time = now
        healthy_threshold = self._target_fps * 0.9
        degraded_threshold = self._target_fps * 0.5

        if was_disconnected:
            self._healthy_since = now if fps >= healthy_threshold else None
            self._below_healthy_since = None
            return self._set(StreamState.RECOVERING, bitrate_kbps, 'frames_resumed', fps)

        if fps >= healthy_threshold:
            self._below_healthy_since = None
            if self._healthy_since is None:
                self._healthy_since = now
            if now - self._healthy_since >= self._healthy_after:
                return self._set(StreamState.HEALTHY, bitrate_kbps, 'healthy', fps)
            return self._set(StreamState.RECOVERING, bitrate_kbps, 'healthy_gate', fps)

        self._healthy_since = None
        if fps < degraded_threshold:
            self._below_healthy_since = now
            return self._set(StreamState.DEGRADED, bitrate_kbps, 'low_fps', fps)
        if self._below_healthy_since is None:
            self._below_healthy_since = now
        if now - self._below_healthy_since >= 10.0:
            return self._set(StreamState.DEGRADED, bitrate_kbps, 'below_target_fps', fps)
        return self._set(StreamState.RECOVERING, bitrate_kbps, 'below_healthy_threshold', fps)

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
    ) -> HealthSnapshot:
        self._snapshot = HealthSnapshot(
            state=state,
            fps=self._snapshot.fps if fps is None else fps,
            bitrate_kbps=bitrate_kbps,
            last_frame_monotonic=self._last_frame_time,
            reason=reason,
        )
        return self._snapshot
