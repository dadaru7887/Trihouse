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


@dataclass(frozen=True)
class SafetyInputs:
    sensor_fresh: bool = True
    # 보호 필드(로봇 폭 직사각형) 안에서 가장 가까운 것까지의 전방 거리.
    # 경로 위에 있는 것만 여기 들어온다 — 좁은 통로의 옆벽은 제외된다.
    front_distance_m: float | None = None
    # 제자리 회전이 쓸고 갈 원 안에 무언가 있는가. 회전은 옆을 치므로 경로
    # 판정으로는 잡히지 않는다.
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
    stop_distance_m: float = 0.30
    slow_distance_m: float = 0.70
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
    person_in_zone = inputs.person_detected or (inputs.person_distance_m is not None and inputs.person_distance_m <= config.person_protective_distance_m)
    # 경로 위의 물체는 STOP 전에 먼저 예고된다. 경로 밖은 감속 근거가 아니다.
    if person_in_zone or (inputs.front_distance_m is not None and inputs.front_distance_m <= config.slow_distance_m):
        return SafetyDecision(SafetyLevel.SLOW, MotionCommand(min(command.linear_x, config.slow_linear_speed_mps), command.angular_z), True, "protective_zone")
    return SafetyDecision(SafetyLevel.CLEAR, command, True, "clear")
