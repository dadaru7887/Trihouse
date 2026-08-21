"""사람 모델 관측 결과를 결정적으로 후처리하는 정책.

GPU model은 box·pose·tracking ID·움직임을 제공한다. 이 module은 안전 규칙만 적용하며
로봇을 직접 구동하지 않는다.
"""

from dataclasses import dataclass

from model.worker.person.fall_monitor import FallMonitor, FallState, MonitorConfig


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
    """관측에 ROI·시간축 규칙을 적용한다. 로봇을 직접 구동하지 않는다.

    낙상 판정은 `fall_monitor.FallMonitor` 하나만 쓴다. 전에는 여기에 별도의
    "낮은 자세가 N 초 지속" 규칙이 있었는데, 같은 판단을 두 곳에서 서로 다르게
    내리는 상태였다. 실측으로 튜닝되고 시험된 쪽(`FallMonitor`)을 남긴다 —
    그쪽에는 노이즈 한 프레임이 쌓인 증거를 지우지 않게 하는
    `recovery_confirm_seconds` 가 있고 `NORMAL … EMERGENCY_CANDIDATE` 다섯 상태가 있다.

    track 마다 monitor 를 따로 둔다. 두 사람이 한 화면에 있으면 한 사람의 회복이
    다른 사람의 증거를 지워서는 안 된다.
    """

    def __init__(
        self,
        *,
        required_consecutive_frames: int,
        monitor: MonitorConfig | None = None,
    ) -> None:
        if required_consecutive_frames < 1:
            raise ValueError('invalid person policy thresholds')
        self._required_frames = required_consecutive_frames
        self._monitor_config = monitor or MonitorConfig()
        self._roi_frames: dict[tuple[str, str, str], int] = {}
        self._fall_monitors: dict[tuple[str, str], FallMonitor] = {}

    def observe_roi(self, observation: PersonObservation, roi: PolygonRoi) -> RoiPresenceEvent:
        overlaps = self._box_overlaps_polygon(observation.box, roi.points)
        key = (observation.camera_id, observation.track_id, roi.roi_id)
        frames = self._roi_frames.get(key, 0) + 1 if overlaps else 0
        self._roi_frames[key] = frames
        return RoiPresenceEvent(observation.camera_id, observation.track_id, roi.roi_id, observation.timestamp_s, overlaps, frames >= self._required_frames)

    def observe_fall(self, observation: PersonObservation) -> FallSuspectedEvent | None:
        """확정 후보에 처음 도달한 순간에만 이벤트를 낸다. 그 외에는 `None`.

        `low_posture` 와 `moving` 은 이미 재어진 값이다 — 지금은
        `posture.py` 의 규칙이, 나중에는 자세 모델이 채운다. 이 함수는 그것을
        다시 재지 않는다.
        """
        result = self._advance(observation)
        if not result['event']:
            return None
        return FallSuspectedEvent(observation.camera_id, observation.track_id, observation.timestamp_s)

    def fall_state(self, observation: PersonObservation) -> str:
        """지금 상태 이름. 이벤트 없이 진행 상황만 보고 싶을 때 쓴다."""
        return self._advance(observation)['state']

    def _advance(self, observation: PersonObservation) -> dict:
        key = (observation.camera_id, observation.track_id)
        monitor = self._fall_monitors.get(key)
        if monitor is None:
            monitor = FallMonitor(self._monitor_config)
            self._fall_monitors[key] = monitor
        return monitor.advance(
            observation.timestamp_s,
            fallen=observation.low_posture,
            low_motion=not observation.moving,
        )

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
