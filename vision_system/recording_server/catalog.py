"""H.264 녹화 process와 분리된 카메라 segment 카탈로그.

recorder는 60초 파일의 시작/종료를 이 카탈로그에 알리고, UI는 재생 중 segment를 표시한다.
삭제 후보는 완료됐고 재생 중이 아닌 segment로만 제한한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SegmentState(StrEnum):
    RECORDING = 'RECORDING'
    COMPLETE = 'COMPLETE'


@dataclass
class RecordingSegment:
    segment_id: str
    camera_id: str
    minute_start_s: int
    size_bytes: int
    state: SegmentState = SegmentState.RECORDING
    playing: bool = False


class RecordingCatalog:
    SEGMENT_DURATION_S = 60

    def __init__(self, *, capacity_bytes: int, recording_root: str = 'recordings') -> None:
        if capacity_bytes <= 0:
            raise ValueError('capacity_bytes must be positive')
        if not recording_root:
            raise ValueError('recording_root is required')
        self._capacity_bytes = capacity_bytes
        self._recording_root = recording_root.rstrip('/')
        self._segments: dict[str, RecordingSegment] = {}

    def start_segment(self, camera_id: str, minute_start_s: int, size_bytes: int) -> RecordingSegment:
        if not camera_id or minute_start_s % self.SEGMENT_DURATION_S or size_bytes < 0:
            raise ValueError('invalid recording segment')
        segment_id = f'{camera_id}:{minute_start_s}'
        if segment_id in self._segments:
            raise ValueError('segment already exists')
        segment = RecordingSegment(segment_id, camera_id, minute_start_s, size_bytes)
        self._segments[segment_id] = segment
        return segment

    def complete(self, segment_id: str) -> RecordingSegment:
        segment = self._segment(segment_id)
        segment.state = SegmentState.COMPLETE
        return segment

    def set_playing(self, segment_id: str, playing: bool) -> RecordingSegment:
        segment = self._segment(segment_id)
        segment.playing = playing
        return segment

    def lookup(self, camera_id: str, *, timestamp_s: float) -> RecordingSegment | None:
        minute_start = int(timestamp_s // self.SEGMENT_DURATION_S) * self.SEGMENT_DURATION_S
        return self._segments.get(f'{camera_id}:{minute_start}')

    def enforce_retention(self) -> tuple[str, ...]:
        deleted: list[str] = []
        candidates = sorted(
            (segment for segment in self._segments.values() if segment.state == SegmentState.COMPLETE and not segment.playing),
            key=lambda segment: (segment.minute_start_s, segment.segment_id),
        )
        for segment in candidates:
            if self._total_size_bytes() <= self._capacity_bytes:
                break
            del self._segments[segment.segment_id]
            deleted.append(segment.segment_id)
        return tuple(deleted)

    def get(self, segment_id: str) -> RecordingSegment | None:
        return self._segments.get(segment_id)

    def recording_path(self, segment: RecordingSegment | None) -> str:
        if segment is None:
            return ''
        return f'{self._recording_root}/{segment.camera_id}/{segment.minute_start_s}.h264'

    def _total_size_bytes(self) -> int:
        return sum(segment.size_bytes for segment in self._segments.values())

    def _segment(self, segment_id: str) -> RecordingSegment:
        try:
            return self._segments[segment_id]
        except KeyError as error:
            raise ValueError(f'unknown recording segment {segment_id}') from error
