"""검증된 배터리 상태를 로봇의 작업 가능 상태로 투영하는 순수 정책."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BatteryProjection:
    state: str
    ready: bool
    reason_code: str


def classify_battery(
    percentage: float, *, valid: bool, charging: bool = False,
) -> BatteryProjection:
    if not valid or not 0.0 <= percentage <= 100.0:
        return BatteryProjection("UNKNOWN", False, "BATTERY_TELEMETRY_INVALID")
    if charging:
        return BatteryProjection("CHARGING", False, "BATTERY_CHARGING")
    if percentage <= 10.0:
        return BatteryProjection(
            "RETURN_REQUIRED", False, "BATTERY_AT_OR_BELOW_RETURN_THRESHOLD",
        )
    if percentage <= 20.0:
        return BatteryProjection("LOCAL_ONLY", True, "BATTERY_LOCAL_WORK_ONLY")
    return BatteryProjection("NORMAL", True, "BATTERY_NORMAL")
