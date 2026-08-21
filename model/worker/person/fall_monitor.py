from dataclasses import dataclass
from enum import Enum
from math import hypot


class FallState(str, Enum):
    NORMAL = "NORMAL"
    FALL_SUSPECTED = "FALL_SUSPECTED"
    FALLEN = "FALLEN"
    IMMOBILE = "IMMOBILE"
    EMERGENCY_CANDIDATE = "EMERGENCY_CANDIDATE"


@dataclass(frozen=True)
class MonitorConfig:
    fall_aspect_ratio: float = 1.2
    fall_confirm_seconds: float = 1.0
    immobile_seconds: float = 5.0
    motion_threshold: float = 0.015
    # Once FALLEN/IMMOBILE/EMERGENCY_CANDIDATE evidence has accumulated, a single
    # noisy "not fallen" frame must not erase it immediately (segmentation aspect
    # ratio is noisy frame-to-frame). Recovery to NORMAL from those states requires
    # this many continuous seconds of "not fallen" readings, mirroring how entry
    # into FALLEN is itself debounced by fall_confirm_seconds.
    recovery_confirm_seconds: float = 1.0


class FallMonitor:
    def __init__(self, config: MonitorConfig) -> None:
        self.config = config
        self.state = FallState.NORMAL
        self.since = 0.0
        self.last_centroid: tuple[float, float] | None = None
        self.event_sent = False
        self.recovery_since: float | None = None

    def update(self, timestamp: float, aspect_ratio: float, centroid: tuple[float, float], frame_diagonal: float) -> dict:
        """측정과 상태 전이를 한 번에. 측정이 이미 있으면 `advance` 를 직접 쓴다."""
        motion = 0.0 if self.last_centroid is None else hypot(centroid[0] - self.last_centroid[0], centroid[1] - self.last_centroid[1]) / max(frame_diagonal, 1.0)
        self.last_centroid = centroid
        result = self.advance(
            timestamp,
            fallen=aspect_ratio >= self.config.fall_aspect_ratio,
            low_motion=motion <= self.config.motion_threshold,
        )
        result["motion"] = motion
        return result

    def advance(self, timestamp: float, fallen: bool, low_motion: bool) -> dict:
        """시간축 상태 전이만 한다. 자세·움직임 **판정은 이미 끝나 있다.**

        `posture.py` 가 재고 여기서 결론을 낸다. 둘을 나눈 이유는 자세 판정이
        언젠가 규칙에서 모델로 바뀌기 때문이다 — 그때 이 파일은 그대로 둔다.
        """
        previous = self.state
        if not fallen:
            if self.state in (FallState.NORMAL, FallState.FALL_SUSPECTED):
                # Nothing safety-critical accumulated yet: drop immediately.
                self.state, self.since, self.event_sent = FallState.NORMAL, timestamp, False
                self.recovery_since = None
            else:
                # FALLEN / IMMOBILE / EMERGENCY_CANDIDATE: require sustained recovery.
                if self.recovery_since is None:
                    self.recovery_since = timestamp
                elif timestamp - self.recovery_since >= self.config.recovery_confirm_seconds:
                    self.state, self.since, self.event_sent = FallState.NORMAL, timestamp, False
                    self.recovery_since = None
        else:
            self.recovery_since = None
            if self.state == FallState.NORMAL:
                self.state, self.since = FallState.FALL_SUSPECTED, timestamp
            elif self.state == FallState.FALL_SUSPECTED and timestamp - self.since >= self.config.fall_confirm_seconds:
                self.state, self.since = FallState.FALLEN, timestamp
            elif self.state == FallState.FALLEN and low_motion:
                self.state, self.since = FallState.IMMOBILE, timestamp
            elif self.state == FallState.IMMOBILE and not low_motion:
                self.state, self.since = FallState.FALLEN, timestamp
            elif self.state == FallState.IMMOBILE and timestamp - self.since >= self.config.immobile_seconds:
                self.state = FallState.EMERGENCY_CANDIDATE
        event = self.state == FallState.EMERGENCY_CANDIDATE and not self.event_sent
        if event:
            self.event_sent = True
        return {"state": self.state.value, "previous_state": previous.value, "motion": 0.0, "event": event}
