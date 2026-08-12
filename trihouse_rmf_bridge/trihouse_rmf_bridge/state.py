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

    def validate(self, now_ns: int, timeout_ns: int) -> StateValidation:
        if not self.robot_id or not self.map_name:
            return StateValidation(False, "PINKY_ID_OR_MAP_MISSING")
        if timeout_ns < 0 or self.observed_at_ns > now_ns or now_ns - self.observed_at_ns > timeout_ns:
            return StateValidation(False, "PINKY_STATUS_STALE")
        if not all(isfinite(value) for value in self.rmf_position):
            return StateValidation(False, "PINKY_POSE_INVALID")
        if not isfinite(self.battery_percentage) or not 0.0 <= self.battery_percentage <= 100.0:
            return StateValidation(False, "PINKY_BATTERY_INVALID")
        if not self.ready:
            return StateValidation(False, "PINKY_NOT_READY")
        return StateValidation(True, "OK")
