"""프레임 한 장의 사람 전원을 사람별 상태로 평가한다.

전까지는 두 호출부가 각자 `select_best` 로 가장 확신 높은 사람 하나만 골라
`FallMonitor` 하나에 넣었다. 그러면 한 화면에 두 사람이 있을 때 한 사람의
회복이 다른 사람의 증거를 지운다 — 서 있는 사람이 매 프레임 골라지면 바닥에
누운 사람의 상태가 계속 리셋된다.

track 별 상태 자체는 `policy.PersonPolicy` 가 이미 갖고 있었다. 여기서 하는
일은 검출 → 자세 측정 → 그 정책으로 잇고, 프레임 하나의 결론을 하나로
줄이는 것뿐이다.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence

from model.perception.segmentation.runtime.detector import select_best
from model.worker.person.fall_monitor import FallState, MonitorConfig
from model.worker.person.policy import (
    BoundingBox, FallSuspectedEvent, PersonObservation, PersonPolicy,
)
from model.worker.person.posture import PostureConfig, TrackedPostureEstimator


NO_DETECTION = "NO_DETECTION"

# 로봇이 반응해야 하는 것은 그 화면에서 가장 나쁜 상태다. 서 있는 행인이
# 바닥에 누운 사람을 가려서는 안 된다.
_SEVERITY = {
    NO_DETECTION: -1,
    FallState.NORMAL.value: 0,
    FallState.FALL_SUSPECTED.value: 1,
    FallState.FALLEN.value: 2,
    FallState.IMMOBILE.value: 3,
    FallState.EMERGENCY_CANDIDATE.value: 4,
}


@dataclass(frozen=True)
class FrameVerdict:
    """프레임 하나의 결론. `track_id` 는 그 상태를 만든 사람이다."""

    state: str
    confidence: float
    track_id: str
    events: tuple[FallSuspectedEvent, ...]


class PersonFrameEvaluator:
    def __init__(self, *, camera_id: str, posture: PostureConfig, monitor: MonitorConfig,
                 track_timeout_seconds: float = 3.0,
                 required_consecutive_frames: int = 3) -> None:
        self.camera_id = camera_id
        self.person_class_id_source = None
        self._posture = TrackedPostureEstimator(posture)
        self._policy = PersonPolicy(
            required_consecutive_frames=required_consecutive_frames,
            monitor=monitor,
            track_timeout_seconds=track_timeout_seconds,
        )

    def evaluate(self, detections: Sequence[Any], frame_shape: tuple[int, ...],
                 timestamp_s: float, *, person_class_id: int = 1) -> FrameVerdict:
        people = [item for item in detections if item.class_id == person_class_id]
        if any(not item.track_id for item in people):
            # tracking 이 꺼져 있으면 프레임을 넘는 신원이 없다. 전원을 빈
            # track_id 하나에 몰아 넣으면 지금 고치려는 그 버그가 그대로
            # 재현되므로, 그때는 예전처럼 확신 높은 한 사람만 본다.
            best = select_best(people, person_class_id)
            people = [best] if best is not None else []

        diagonal = math.hypot(frame_shape[1], frame_shape[0])
        seen: set[str] = set()
        best_state, best_confidence, best_track = NO_DETECTION, 0.0, ""
        events: list[FallSuspectedEvent] = []

        for person in people:
            measurement = self._posture.measure(person.track_id, person.mask, diagonal)
            if measurement is None:
                continue
            seen.add(person.track_id)
            observation = PersonObservation(
                camera_id=self.camera_id,
                track_id=person.track_id,
                timestamp_s=timestamp_s,
                box=_bounding_box(person.mask),
                confidence=float(person.confidence),
                low_posture=measurement.low_posture,
                moving=measurement.moving,
            )
            # 한 관측으로 상태와 이벤트를 함께 받는다. 따로 물으면 시간축이
            # 한 프레임에 두 칸 나가서 FALLEN 을 건너뛰고 IMMOBILE 이 된다.
            result = self._policy.observe(observation)
            if result['event'] is not None:
                events.append(result['event'])
            state = result['state']
            if _SEVERITY[state] > _SEVERITY[best_state]:
                best_state = state
                best_confidence = float(person.confidence)
                best_track = person.track_id

        self._posture.forget_missing(seen)
        self._policy.note_present_tracks(self.camera_id, seen, timestamp_s)
        return FrameVerdict(best_state, best_confidence, best_track, tuple(events))


def _bounding_box(mask: Any) -> BoundingBox:
    import numpy as np

    ys, xs = np.nonzero(mask)
    return BoundingBox(float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))
