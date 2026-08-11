"""전압 추정이 아닌 실측 경로 소비량으로 새 작업을 제한하는 FMS 배터리 정책."""

from enum import StrEnum


class BatteryDecision(StrEnum):
    CONTINUE = 'CONTINUE'
    COMPLETE_THEN_RETURN = 'COMPLETE_THEN_RETURN'
    HOLD_CURRENT_AND_RETURN = 'HOLD_CURRENT_AND_RETURN'
    IMMEDIATE_RETURN = 'IMMEDIATE_RETURN'


class BatteryStatus(StrEnum):
    NORMAL = 'NORMAL'
    WORK_LIMITED = 'WORK_LIMITED'
    RETURN_REQUIRED = 'RETURN_REQUIRED'


class BatteryPolicy:
    def __init__(
        self,
        *,
        return_threshold_percent: float,
        emergency_threshold_percent: float,
        consumption_percent_per_m: float,
        safety_margin_percent: float,
    ) -> None:
        if not 0 <= emergency_threshold_percent <= return_threshold_percent <= 100:
            raise ValueError('battery thresholds are invalid')
        if consumption_percent_per_m <= 0 or safety_margin_percent < 0:
            raise ValueError('consumption and margin are invalid')
        self._return_threshold = return_threshold_percent
        self._emergency_threshold = emergency_threshold_percent
        self._consumption = consumption_percent_per_m
        self._margin = safety_margin_percent

    def decide(self, *, battery_percent: float, remaining_current_m: float, return_to_charge_m: float, has_cargo: bool) -> BatteryDecision:
        if battery_percent < 0 or remaining_current_m < 0 or return_to_charge_m < 0:
            raise ValueError('battery and route distance must be non-negative')
        if battery_percent <= self._emergency_threshold:
            return BatteryDecision.IMMEDIATE_RETURN
        required = (remaining_current_m + return_to_charge_m) * self._consumption + self._margin
        if battery_percent >= required:
            after_current = battery_percent - (remaining_current_m * self._consumption + self._margin)
            if has_cargo and after_current <= self._return_threshold:
                return BatteryDecision.COMPLETE_THEN_RETURN
            return BatteryDecision.CONTINUE
        return BatteryDecision.HOLD_CURRENT_AND_RETURN

    def status(self, battery_percent: float) -> BatteryStatus:
        if battery_percent < 0:
            raise ValueError('battery_percent must be non-negative')
        if battery_percent <= self._emergency_threshold:
            return BatteryStatus.RETURN_REQUIRED
        if battery_percent <= self._return_threshold:
            return BatteryStatus.WORK_LIMITED
        return BatteryStatus.NORMAL

    def can_accept_new_job(self, *, battery_percent: float, job_distance_m: float, return_to_charge_m: float) -> bool:
        """작업 완료 후 복귀 여유까지 남는 경우에만 새 작업을 허용한다."""
        if job_distance_m < 0 or return_to_charge_m < 0:
            raise ValueError('route distances must be non-negative')
        if self.status(battery_percent) == BatteryStatus.RETURN_REQUIRED:
            return False
        required = (job_distance_m + return_to_charge_m) * self._consumption + self._margin
        return battery_percent >= required
