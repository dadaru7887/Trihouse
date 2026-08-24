"""테스트 가능한 최종 속도 gate 순수 정책.

ROS node가 latch와 subscription을 맡고, 이 module은 한 관측 시점의 안전 출력만 결정한다.
"""

from dataclasses import dataclass
from enum import IntEnum


class SafetyLevel(IntEnum):
    CLEAR = 0
    SLOW = 1
    STOP = 2
    EMERGENCY = 3


@dataclass(frozen=True)
class MotionCommand:
    linear_x: float
    angular_z: float


def select_motion_source(
    nav: MotionCommand,
    dock: MotionCommand | None,
    *,
    now_s: float,
    dock_received_at_s: float,
    dock_timeout_s: float,
) -> MotionCommand:
    """도킹 속도는 새 관측 제어 주기 안에서만 Nav2보다 우선한다.

    marker dock action은 완료/취소 때 zero Twist를 한 번 발행한다. 그 값을
    무기한 우선하면 이후 Nav2가 영구 정지하므로, stale dock은 의도적으로 버린다.
    """
    if (
        dock is not None
        and dock_timeout_s > 0.0
        and 0.0 <= now_s - dock_received_at_s <= dock_timeout_s
    ):
        return dock
    return nav


def select_manual_command(
    command: MotionCommand,
    *,
    now_s: float,
    received_at_s: float,
    timeout_s: float,
) -> MotionCommand:
    """Local-manual 입력은 새 키보드 명령이 끊기면 반드시 정지한다."""
    if timeout_s > 0.0 and 0.0 <= now_s - received_at_s <= timeout_s:
        return command
    return MotionCommand(0.0, 0.0)


@dataclass(frozen=True)
class SafetyInputs:
    sensor_fresh: bool = True
    # 보호 필드(로봇 폭 직사각형) 안에서 가장 가까운 것까지의 전방 거리.
    # 경로 위에 있는 것만 여기 들어온다 — 좁은 통로의 옆벽은 제외된다.
    front_distance_m: float | None = None
    # 제자리 회전할 때 **몸에 닿을 만큼 가까운 것**이 있는가.
    #
    # 원래는 "회전이 쓸고 갈 원 안에 무언가 있는가" 였다. 그 판정은 Nav2 가
    # local costmap 위에서 발자국을 실제로 돌려 검사하는 것과 겹치고, 원 하나로
    # 근사하는 만큼 언제나 더 보수적이다. 지금 여기 남은 것은 costmap 에 없는
    # 물체(끌려 나온 케이블 등)만 잡는 접촉 감지다 — 근거는
    # `geometry.SWEPT_CONTACT_M` 의 주석에 있다.
    swept_blocked: bool = False
    # 감속의 근거는 **사람**이지 벽이 아니다. 벽은 지도에 있는 정적 장애물이고
    # 옆을 스치는 것뿐이라, 그것으로 속도를 낮추면 2.20 x 2.70 m 방에서는 늘
    # 낮춘 상태가 된다. 사람은 카메라(`PersonDetection`)가 알려 준다.
    person_detected: bool = False
    person_distance_m: float | None = None
    keep_out: bool = False
    emergency_latched: bool = False
    control_link_fresh: bool = True


@dataclass(frozen=True)
class SafetyConfig:
    # 몸 끝에서 잰 값이다 (`path_clearance` 가 발자국을 이미 뺀다). 2.20 x 2.70 m
    # 방에서는 어느 다리든 벽이 곧 목적지라, 이 값이 크면 도착 전에 STOP 이 걸린다.
    stop_distance_m: float = 0.05
    # **지금은 판정에 쓰이지 않는다.** `apply_safety_gate` 의 주석 처리된 절을
    # 되살릴 때만 의미가 생긴다. 값을 0.70 에서 0.25 로 내려 둔 이유는, 되살리는
    # 사람이 옛 값을 그대로 쓰면 아래 주석에 적힌 상시 감속이 그대로 재현되기
    # 때문이다.
    slow_distance_m: float = 0.25
    slow_linear_speed_mps: float = 0.08
    person_protective_distance_m: float = 1.0


@dataclass(frozen=True)
class SafetyDecision:
    level: SafetyLevel
    command: MotionCommand
    goal_may_continue: bool
    reason: str


def apply_safety_gate(command: MotionCommand, inputs: SafetyInputs, config: SafetyConfig = SafetyConfig()) -> SafetyDecision:
    """Return a bounded command; STOP deliberately does not cancel Nav2's goal."""
    if inputs.emergency_latched:
        return SafetyDecision(SafetyLevel.EMERGENCY, MotionCommand(0.0, 0.0), False, "emergency_latched")
    # 관제 연결이 끊기면 checkpoint 대조 전까지 계속 주행하지 않는다.
    if not inputs.control_link_fresh:
        return SafetyDecision(SafetyLevel.STOP, MotionCommand(0.0, 0.0), True, "control_link_lost")
    if not inputs.sensor_fresh:
        return SafetyDecision(SafetyLevel.STOP, MotionCommand(0.0, 0.0), True, "sensor_timeout")
    if inputs.keep_out:
        return SafetyDecision(SafetyLevel.STOP, MotionCommand(0.0, 0.0), True, "keep_out")
    # 회전은 외접원 전체를 쓸고 지나간다. 옆에 있는 것이 곧 부딪히는 것이라
    # 경로(직사각형) 판정으로는 잡히지 않는다.
    if inputs.swept_blocked:
        return SafetyDecision(SafetyLevel.STOP, MotionCommand(0.0, 0.0), True, "swept_stop")
    if inputs.front_distance_m is not None and inputs.front_distance_m <= config.stop_distance_m:
        return SafetyDecision(SafetyLevel.STOP, MotionCommand(0.0, 0.0), True, "front_stop")
    # 사람이 **보호 거리 안에** 있는가.
    #
    # 이전에는 `person_detected or (거리 <= 임계)` 였다. `or` 이라 거리 조건이
    # 아무 것도 거르지 못했고, node 가 미검출일 때 거리에 None 을 넣으므로
    # 사실상 `person_in_zone == person_detected` 였다 — 방 반대편에 선 참관자,
    # 로봇 **뒤**에 있는 사람, 신뢰도 0.01 짜리 오검출까지 전부 감속을 걸었다.
    # 운영 테스트는 사람이 옆에서 지켜보므로 상시 감속이 된다.
    #
    # 거리를 모를 때(None)는 감속한다 — 모르는 것을 안전하다고 읽지 않는다.
    person_in_zone = inputs.person_detected and (
        inputs.person_distance_m is None
        or inputs.person_distance_m <= config.person_protective_distance_m
    )
    # 감속의 근거는 **사람뿐**이다.
    #
    # 아래 주석 처리된 절이 경로 위 거리로도 감속을 걸던 것이다. 그것은 Nav2 가
    # 이미 더 나은 정보로 하는 일과 완전히 겹친다 —
    # `use_cost_regulated_linear_velocity_scaling`(cost_scaling_dist 0.6) 과
    # `approach_velocity_scaling_dist`(0.6) 두 개가 costmap 위에서 돌고 있다.
    # 여기서 세 번째로 같은 일을 하면 감속만 3 중이 된다. 2.20 x 2.70 m 방에서는
    # 어느 지점이든 목적지 또는 장애물의 0.6 m 안이라 셋이 항상 동시에 걸리고,
    # `desired_linear_vel: 0.2` 가 실제로는 0.05~0.08 로 떨어진다.
    #
    # 되살리려면 아래 한 줄의 주석을 풀고 `slow_distance_m` 을 방 크기보다 작게
    # 둔다. 다만 그 전에 Nav2 쪽 두 파라미터를 먼저 확인하는 것이 순서다.
    #
    #     or (inputs.front_distance_m is not None
    #         and inputs.front_distance_m <= config.slow_distance_m)
    if person_in_zone:
        # `min` 이 아니라 크기 clamp 다. `min(-0.20, 0.08)` 은 -0.20 을 그대로
        # 통과시키므로 **후진에서는 감속이 아예 걸리지 않았다.** 부호는 진행
        # 방향이고 상한은 빠르기이므로, 둘을 갈라서 적용해야 한다.
        limit = config.slow_linear_speed_mps
        limited_x = max(-limit, min(command.linear_x, limit))
        return SafetyDecision(SafetyLevel.SLOW, MotionCommand(limited_x, command.angular_z), True, "protective_zone")
    return SafetyDecision(SafetyLevel.CLEAR, command, True, "clear")
