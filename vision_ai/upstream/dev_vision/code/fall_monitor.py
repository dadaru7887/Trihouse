"""시간축 상태전이 -- dadaru7887/Trihouse(dev) model/worker/person/fall_monitor.py를
그대로 가져옴(2026-08-23). 자세/움직임 판정은 이미 끝나 있다고 가정하고 시간축
전이만 담당 -- video_monitor.py가 판정(분류기+규칙 OR)을 만들어서 advance()에 넣음.
"""

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
    fall_aspect_ratio: float = 0.9
    fall_confirm_seconds: float = 1.0
    immobile_seconds: float = 5.0
    motion_threshold: float = 0.015
    # FALLEN/IMMOBILE/EMERGENCY_CANDIDATE 상태에서 노이즈 한 프레임에 즉시 리셋되지
    # 않도록, NORMAL로 돌아가려면 이 시간만큼 연속으로 "안 넘어짐" 판정이 나와야 함.
    recovery_confirm_seconds: float = 1.0
    # aspect_ratio가 프레임 사이 이 값 이상 바뀌면 "자세가 바뀌는 중"으로 보고
    # low_motion=False 취급(centroid 기반 motion만 쓰면 제자리에서 일어나는 동작을
    # "안 움직임"으로 오판함 -- 2026-08-24 162744 실측: 9초에 일어났는데 위치가
    # 거의 안 바뀌어서 IMMOBILE이 안 풀리고 9.15초에 오탐 발생). 미검증값, 시도값.
    posture_change_threshold: float = 0.15


class FallMonitor:
    def __init__(self, config: MonitorConfig) -> None:
        self.config = config
        self.state = FallState.NORMAL
        self.since = 0.0
        # FALLEN 계열(FALLEN/IMMOBILE)에 "처음" 진입한 시각. FALLEN<->IMMOBILE 내부
        # 전이로는 리셋 안 됨(NORMAL로 완전히 돌아갈 때만 리셋) -- immobile_seconds
        # 판정을 여기 기준으로 함. 2026-08-24 170622 실측으로 발견: 숨쉬기 등 미세한
        # 움직임 때문에 FALLEN/IMMOBILE이 짧은 주기로 계속 왔다갔다 하면, 매번
        # self.since가 리셋돼서 14초 넘게 실제로 쓰러져 있었는데도 5초 연속을 한
        # 번도 못 채워 EMERGENCY_CANDIDATE가 영영 안 뜨는 버그가 있었음.
        self.fallen_since: float | None = None
        self.last_centroid: tuple[float, float] | None = None
        self.event_sent = False
        self.recovery_since: float | None = None

    def note_no_detection(self) -> None:
        """탐지가 끊긴 프레임(사람이 안 잡힘)에서 호출. state/since는 안 건드림 --
        다시 나타났을 때도 계속 쓰러져 있을 수 있어서 "쓰러짐" 판정 자체는 유지해야
        함. 대신 recovery_since는 리셋함 -- 안 그러면 사람이 사라진 동안 흐른
        wall-clock 시간이 "recovery_confirm_seconds 이상 정상이었다"는 증거로
        잘못 인정돼서, 다시 나타났을 때 실제 회복 여부와 상관없이 한 프레임 만에
        NORMAL로 튀는 버그가 생김(2026-08-24 실측으로 발견: 낙상 후 사람이 화면
        밖으로 나갔다가 4초 뒤 다시 잡혔는데, recovery_since가 사라지기 직전
        시각에 멈춰있던 탓에 그 4초가 통째로 recovery_confirm_seconds를 만족시켜
        버려서 즉시 NORMAL 전환됨 -- 결과적으로 우연히 정답이었지만 재현성 없는
        우연이었음)."""
        self.recovery_since = None

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
        """시간축 상태 전이만 한다. 자세·움직임 판정은 이미 끝나 있다."""
        previous = self.state
        if not fallen:
            if self.state in (FallState.NORMAL, FallState.FALL_SUSPECTED):
                self.state, self.since, self.event_sent = FallState.NORMAL, timestamp, False
                self.recovery_since = None
                self.fallen_since = None
            else:
                if self.recovery_since is None:
                    self.recovery_since = timestamp
                elif timestamp - self.recovery_since >= self.config.recovery_confirm_seconds:
                    self.state, self.since, self.event_sent = FallState.NORMAL, timestamp, False
                    self.recovery_since = None
                    self.fallen_since = None
        else:
            self.recovery_since = None
            if self.state == FallState.NORMAL:
                self.state, self.since = FallState.FALL_SUSPECTED, timestamp
            elif self.state == FallState.FALL_SUSPECTED and timestamp - self.since >= self.config.fall_confirm_seconds:
                self.state, self.since = FallState.FALLEN, timestamp
                self.fallen_since = timestamp
            elif self.state == FallState.FALLEN and low_motion:
                self.state, self.since = FallState.IMMOBILE, timestamp
            elif self.state == FallState.IMMOBILE and not low_motion:
                self.state, self.since = FallState.FALLEN, timestamp
            elif (
                self.state == FallState.IMMOBILE and self.fallen_since is not None
                and timestamp - self.fallen_since >= self.config.immobile_seconds
            ):
                self.state = FallState.EMERGENCY_CANDIDATE
        event = self.state == FallState.EMERGENCY_CANDIDATE and not self.event_sent
        if event:
            self.event_sent = True
        return {"state": self.state.value, "previous_state": previous.value, "motion": 0.0, "event": event}
