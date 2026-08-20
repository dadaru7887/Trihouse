"""Pinky telemetry를 Open-RMF 입력으로 바꾸기 전 검증하는 순수 모델."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class StateValidation:
    accepted: bool
    reason_code: str


@dataclass(frozen=True)
class PinkyState:
    robot_id: str
    map_name: str
    x: float
    y: float
    yaw: float
    battery_percentage: float
    ready: bool
    observed_at_ns: int

    @property
    def rmf_position(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.yaw)

    @property
    def rmf_soc(self) -> float:
        return self.battery_percentage / 100.0

    def validate(
        self, now_ns: int, timeout_ns: int, *, executing: bool = False
    ) -> StateValidation:
        """RMF 에 이 상태를 넘겨도 되는지 판단한다.

        판정이 두 갈래인 이유 — **좌표를 믿을 수 없는 것**과 **로봇이 지금 새 작업을
        받을 처지가 아닌 것**은 다른 사실이다.

        앞의 셋(stale / pose / battery)은 값 자체가 거짓이라 어떤 경우에도 넘기지
        않는다. 틀린 자리를 보고하면 RMF 의 교통 계획이 그 거짓 위에 쌓인다.

        마지막 `ready`(= `dispatchable`)는 다르다. 그것은 *"이 로봇에 **새 작업**을
        줘도 되는가"* 이지 *"하던 일을 계속해도 되는가"* 가 아니다. 협로에 들어가면
        통로 벽이 `stop_distance_m`(0.30 m) 안에 들어와 안전 gate 가 STOP 을 걸고,
        `safety_blocked` 로 `dispatchable` 이 false 가 된다. 통로 폭이 0.20 m 이므로
        **매번** 그렇게 된다.

        그때 갱신을 끊으면 RMF 가 명령 핸들을 "응답 없음" 으로 보고 replan → stop →
        cancel 로 작업을 죽인다(`rmf_fleet_adapter/phases/MoveRobot.hpp:170`).
        2026-08-20 시뮬에서 두 번 연속 재현했고, step 20 이 `RMF_TASK_CANCELLED` 로
        닫힌 뒤 러너가 회복 경로 없이 영구히 멈췄다.

        그래서 **수행 중(`executing=True`)에는 `ready` 를 판정에서 뺀다.** 새 작업이
        들어올 걱정은 없다 — EasyFullControl 은 로봇 하나에 작업 하나만 준다.

        Args:
            now_ns: 지금 시각.
            timeout_ns: 이보다 오래된 관측은 stale 이다.
            executing: 로봇이 RMF 명령을 수행하는 중인가.
        """
        if not self.robot_id or not self.map_name:
            return StateValidation(False, "PINKY_ID_OR_MAP_MISSING")
        if timeout_ns < 0 or self.observed_at_ns > now_ns or now_ns - self.observed_at_ns > timeout_ns:
            return StateValidation(False, "PINKY_STATUS_STALE")
        if not all(isfinite(value) for value in self.rmf_position):
            return StateValidation(False, "PINKY_POSE_INVALID")
        if not isfinite(self.battery_percentage) or not 0.0 <= self.battery_percentage <= 100.0:
            return StateValidation(False, "PINKY_BATTERY_INVALID")
        if not self.ready and not executing:
            return StateValidation(False, "PINKY_NOT_READY")
        return StateValidation(True, "OK")
