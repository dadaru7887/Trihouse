"""사람 모델 관측 결과를 결정적으로 후처리하는 정책.

GPU model은 box·pose·tracking ID·움직임을 제공한다. 이 module은 안전 규칙만 적용하며
로봇을 직접 구동하지 않는다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BoundingBox:
    left: float
    top: float
    right: float
    bottom: float

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom


@dataclass(frozen=True)
class PolygonRoi:
    roi_id: str
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class PersonObservation:
    camera_id: str
    track_id: str
    timestamp_s: float
    box: BoundingBox
    confidence: float
    low_posture: bool
    moving: bool


@dataclass(frozen=True)
class RoiPresenceEvent:
    camera_id: str
    track_id: str
    roi_id: str
    timestamp_s: float
    overlaps_roi: bool
    confirmed: bool


@dataclass(frozen=True)
class FallSuspectedEvent:
    camera_id: str
    track_id: str
    timestamp_s: float


class PersonPolicy:
    def __init__(self, *, required_consecutive_frames: int, fall_static_for_s: float) -> None:
        if required_consecutive_frames < 1 or fall_static_for_s < 0:
            raise ValueError('invalid person policy thresholds')
        self._required_frames = required_consecutive_frames
        self._fall_static_for_s = fall_static_for_s
        self._roi_frames: dict[tuple[str, str, str], int] = {}
        self._fall_started_at: dict[tuple[str, str], float] = {}

    def observe_roi(self, observation: PersonObservation, roi: PolygonRoi) -> RoiPresenceEvent:
        overlaps = self._box_overlaps_polygon(observation.box, roi.points)
        key = (observation.camera_id, observation.track_id, roi.roi_id)
        frames = self._roi_frames.get(key, 0) + 1 if overlaps else 0
        self._roi_frames[key] = frames
        return RoiPresenceEvent(observation.camera_id, observation.track_id, roi.roi_id, observation.timestamp_s, overlaps, frames >= self._required_frames)

    def observe_fall(self, observation: PersonObservation) -> FallSuspectedEvent | None:
        key = (observation.camera_id, observation.track_id)
        if not observation.low_posture or observation.moving:
            self._fall_started_at.pop(key, None)
            return None
        started = self._fall_started_at.setdefault(key, observation.timestamp_s)
        if observation.timestamp_s - started < self._fall_static_for_s:
            return None
        return FallSuspectedEvent(observation.camera_id, observation.track_id, observation.timestamp_s)

    @staticmethod
    def _box_overlaps_polygon(box: BoundingBox, polygon: tuple[tuple[float, float], ...]) -> bool:
        if len(polygon) < 3:
            raise ValueError('ROI requires at least three points')
        corners = ((box.left, box.top), (box.right, box.top), (box.right, box.bottom), (box.left, box.bottom))
        return any(PersonPolicy._inside_polygon(corner, polygon) for corner in corners) or any(box.contains(x, y) for x, y in polygon)

    @staticmethod
    def _inside_polygon(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> bool:
        x, y = point
        inside = False
        previous_x, previous_y = polygon[-1]
        for current_x, current_y in polygon:
            crosses = (current_y > y) != (previous_y > y)
            if crosses and x < (previous_x - current_x) * (y - current_y) / (previous_y - current_y) + current_x:
                inside = not inside
            previous_x, previous_y = current_x, current_y
        return inside
