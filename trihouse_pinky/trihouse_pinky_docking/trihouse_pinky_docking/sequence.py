"""좁은 도크에 후진으로 들어가는 규칙 기반 시퀀스. ROS 와 분리해 시험 가능하게 둔다.

## 왜 Nav2 로 안 하는가

RPP 는 후진을 못 한다. `allow_reversing` 은 전역 경로에 **이미** 방향 전환점이
있을 때 그 구간을 뒤로 따라가는 스위치인데, 우리 전역 플래너(NavFn)는 그런 경로를
만들지 않는다. 게다가 `use_rotate_to_heading` 과 동시에 켤 수도 없다 — nav2 가
파라미터 갱신을 거절한다.

더 근본적으로, 냉동 도크 통로는 폭 0.20 m 이고 로봇 회전 지름은 0.34 m 다.
**통로 안에서 도는 것 자체가 불가능하다.** 어떤 컨트롤러도 못 푼다.

풀이는 회전과 후진을 나누는 것이다 — 넓은 곳에서 돌고, 좁은 통로는 곧게 후진으로
들어간다. 후진에는 회전 원이 필요 없고 로봇 폭만 있으면 된다.

## 원본과 달라진 것

`dev_driving` 의 `narrow3_rule_based_docking.py` 는 `/cmd_vel` 을 직접 쐈고 충돌
감지가 없어 *"사람이 옆에서 지켜보다가 Ctrl+C"* 를 전제했다. 여기서 만든 명령은
`cmd_vel_dock` 으로 나가 `safety_supervisor` 아래로 들어간다 — 사람이 지켜보던
자리를 안전 gate 가 대신한다.

거리는 시간이 아니라 **실제 이동량**으로 잰다. gate 가 사람 때문에 감속하면 시간
기준으로는 덜 가서 도크에 못 닿는다.
"""

from dataclasses import dataclass
from math import atan2, cos, hypot, sin

STEP_KINDS = ("rotate", "straight", "exit_zone")


@dataclass(frozen=True)
class SequenceLimits:
    """좁은 통로에서 안전 gate 가 멈출 틈을 남기는 속도 상한.

    원본이 실물에서 쓴 값(0.06 m/s, 0.5 rad/s)을 그대로 쓴다. 이 구간은 여유가
    센티미터 단위라 빠를 이유가 없다.
    """

    max_linear_mps: float = 0.06
    max_angular_rps: float = 0.5
    linear_tolerance_m: float = 0.02
    angular_tolerance_rad: float = 0.05
    # 한 단계가 이 시간 안에 안 끝나면 실패로 본다. 바퀴가 헛돌면 목표 거리에
    # 영원히 못 닿고, 그때 로봇은 도크 안에서 계속 밀어붙인다.
    step_timeout_s: float = 20.0


@dataclass(frozen=True)
class DockCommand:
    linear_x: float = 0.0
    angular_z: float = 0.0


@dataclass(frozen=True)
class DockStep:
    """`kind` 는 `rotate`(목표 yaw), `straight`(부호 있는 거리), `exit_zone`.

    오타를 만들 때 잡는다. 주행 중에 드러나면 로봇이 도크 안에서 멈춘다.
    """

    kind: str
    value: float

    def __post_init__(self) -> None:
        if self.kind not in STEP_KINDS:
            raise ValueError(f"알 수 없는 단계: {self.kind} (가능: {STEP_KINDS})")


def normalize(angle: float) -> float:
    """-pi..pi 로 접는다. 179 도와 -181 도는 같은 방향이다."""
    return atan2(sin(angle), cos(angle))


def in_oriented_zone(x: float, y: float, zone: dict) -> bool:
    """구역 좌표계로 옮겨 직사각형 안인지 본다.

    원이 아니라 방향이 정해진 직사각형인 이유는 통로 진입이 좁고 긴 형태이기
    때문이다. 원으로 잡으면 통로 옆에서도 걸려 엉뚱한 곳에서 후진이 시작된다.
    병목(mutex) 구역이 원인 것과는 성격이 다르다 — 그쪽은 방향과 무관하다.
    """
    dx, dy = x - zone["cx"], y - zone["cy"]
    c, s = cos(-zone["yaw"]), sin(-zone["yaw"])
    along = dx * c - dy * s
    across = dx * s + dy * c
    return abs(along) <= zone["length"] / 2 and abs(across) <= zone["width"] / 2


class DockSequence:
    """단계 목록을 pose 되먹임으로 하나씩 실행한다. 시간이 아니라 이동량이 기준이다."""

    def __init__(self, steps: tuple[DockStep, ...], limits: SequenceLimits) -> None:
        if not steps:
            raise ValueError("시퀀스가 비어 있습니다")
        self.steps = tuple(steps)
        self.limits = limits
        self.step_index = 0
        self.failure: str | None = None
        self._zone: dict | None = None
        self._started = False
        self._step_origin: tuple[float, float] | None = None
        self._step_began_at = 0.0

    @property
    def is_complete(self) -> bool:
        return self._started and self.step_index >= len(self.steps)

    @property
    def is_failed(self) -> bool:
        return self.failure is not None

    def begin(self, *, x: float, y: float, yaw: float, zone: dict, now_s: float = 0.0) -> bool:
        """구역 안에 있을 때만 시작한다. 밖이면 아무것도 하지 않고 False.

        Nav2 가 아직 데려다주지 못했는데 시작하면 엉뚱한 곳에서 후진한다.
        """
        if not in_oriented_zone(x, y, zone):
            return False
        self._zone = zone
        self._started = True
        self._begin_step(x, y, now_s)
        return True

    def _begin_step(self, x: float, y: float, now_s: float) -> None:
        self._step_origin = (x, y)
        self._step_began_at = now_s

    def advance(self, *, x: float, y: float, yaw: float, now_s: float = 0.0) -> DockCommand:
        """지금 pose 로 다음 속도 명령을 낸다. 끝났거나 실패면 0 을 낸다."""
        if not self._started or self.is_complete or self.is_failed:
            return DockCommand()
        if now_s - self._step_began_at > self.limits.step_timeout_s:
            self.failure = "step_timeout"
            return DockCommand()

        step = self.steps[self.step_index]
        if step.kind == "rotate":
            command, done = self._rotate(yaw, step.value)
        elif step.kind == "straight":
            command, done = self._straight(x, y, step.value)
        else:
            command, done = self._exit_zone(x, y)

        if done:
            self.step_index += 1
            self._begin_step(x, y, now_s)
            return DockCommand()
        return command

    def _rotate(self, yaw: float, target_yaw: float) -> tuple[DockCommand, bool]:
        error = normalize(target_yaw - yaw)
        if abs(error) < self.limits.angular_tolerance_rad:
            return DockCommand(), True
        speed = max(-self.limits.max_angular_rps, min(self.limits.max_angular_rps, 1.2 * error))
        # 직진 성분을 섞지 않는다. 좁은 통로 입구에서 옆으로 밀린다.
        return DockCommand(0.0, speed), False

    def _straight(self, x: float, y: float, distance: float) -> tuple[DockCommand, bool]:
        assert self._step_origin is not None
        travelled = hypot(x - self._step_origin[0], y - self._step_origin[1])
        remaining = abs(distance) - travelled
        if remaining <= self.limits.linear_tolerance_m:
            return DockCommand(), True
        sign = 1.0 if distance >= 0 else -1.0
        # 남은 거리에 비례해 줄인다. 끝까지 최고 속도면 허용오차를 넘겨 지나친다.
        speed = min(self.limits.max_linear_mps, 0.6 * remaining)
        return DockCommand(sign * speed, 0.0), False

    def _exit_zone(self, x: float, y: float) -> tuple[DockCommand, bool]:
        """구역을 벗어날 때까지 전진한다. 나갈 거리를 미리 잴 필요가 없다."""
        assert self._zone is not None
        if not in_oriented_zone(x, y, self._zone):
            return DockCommand(), True
        return DockCommand(self.limits.max_linear_mps, 0.0), False
