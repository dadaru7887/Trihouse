"""Parse FFmpeg progress and calculate transport metrics."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProgressSample:
    frame_count: int
    reported_fps: float
    out_time_seconds: float


class FfmpegProgressParser:
    """Collect key/value progress records emitted by ``ffmpeg -progress``."""

    def __init__(self) -> None:
        self._record: dict[str, str] = {}

    def feed(self, line: str) -> ProgressSample | None:
        stripped = line.strip()
        if '=' not in stripped:
            return None
        key, value = stripped.split('=', 1)
        if key not in {'frame', 'fps', 'out_time_us', 'out_time_ms', 'progress'}:
            return None
        if key != 'progress':
            self._record[key] = value
            return None

        try:
            frame_count = int(self._record['frame'])
            reported_fps = float(self._record.get('fps', '0'))
            micros = int(self._record.get('out_time_us', self._record.get('out_time_ms', '0')))
        except (KeyError, ValueError):
            self._record.clear()
            return None
        self._record.clear()
        return ProgressSample(
            frame_count=frame_count,
            reported_fps=reported_fps,
            out_time_seconds=micros / 1_000_000.0,
        )


class EncodedBitrateSampler:
    """Estimate encoded kilobits per second from a monotonic byte counter."""

    def __init__(self) -> None:
        self._last_bytes: int | None = None
        self._last_time: float | None = None

    def sample(self, total_bytes: int | None, now: float) -> float:
        if total_bytes is None:
            self._last_bytes = None
            self._last_time = None
            return 0.0
        if self._last_bytes is None or self._last_time is None:
            self._last_bytes = total_bytes
            self._last_time = now
            return 0.0

        delta_bytes = total_bytes - self._last_bytes
        elapsed = now - self._last_time
        if delta_bytes < 0:
            self._last_bytes = total_bytes
            self._last_time = now
            return 0.0
        if elapsed <= 0:
            return 0.0

        self._last_bytes = total_bytes
        self._last_time = now
        return delta_bytes * 8.0 / elapsed / 1000.0
