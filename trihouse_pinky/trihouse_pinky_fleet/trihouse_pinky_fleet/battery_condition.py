"""`BatteryState` 원본을 검증하고 telemetry freshness를 추적한다."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class BatteryObservation:
    """정책 노드가 신뢰할 수 있도록 검증된 배터리 관측값."""

    percentage: float
    present: bool
    power_supply_status: int
    measurement_valid: bool
    has_valid_sample: bool
    telemetry_fresh: bool
    reason_code: str


class BatteryConditionTracker:
    """첫 유효 sample과 마지막 유효 sample 시각을 단조 시계로 추적한다."""

    def __init__(
        self,
        *,
        started_at: float,
        startup_timeout_s: float = 5.0,
        telemetry_timeout_s: float = 3.0,
    ) -> None:
        self._started_at = started_at
        self._startup_timeout_s = startup_timeout_s
        self._telemetry_timeout_s = telemetry_timeout_s
        self._last_valid_sample_at: float | None = None
        self._percentage = 0.0
        self._present = False
        self._power_supply_status = 0
        self._measurement_valid = False
        self._latest_invalid_reason: str | None = None

    def ingest(
        self,
        *,
        percentage: float,
        present: bool,
        power_supply_status: int,
        received_at: float,
    ) -> BatteryObservation:
        """새 sample을 검증한다. invalid sample은 freshness를 연장하지 않는다."""

        self._present = present
        self._power_supply_status = power_supply_status

        if not present:
            self._measurement_valid = False
            self._latest_invalid_reason = "BATTERY_NOT_PRESENT"
        elif not isfinite(percentage) or not 0.0 <= percentage <= 1.0:
            self._measurement_valid = False
            self._latest_invalid_reason = "BATTERY_PERCENTAGE_INVALID"
        else:
            self._percentage = percentage * 100.0
            self._measurement_valid = True
            self._latest_invalid_reason = None
            self._last_valid_sample_at = received_at

        return self.evaluate(now=received_at)

    def evaluate(self, *, now: float) -> BatteryObservation:
        """현재 시각 기준으로 초기 대기 또는 telemetry 만료 상태를 계산한다."""

        has_valid_sample = self._last_valid_sample_at is not None
        telemetry_fresh = bool(
            has_valid_sample
            and now - self._last_valid_sample_at <= self._telemetry_timeout_s
        )

        if self._latest_invalid_reason == "BATTERY_NOT_PRESENT":
            reason_code = self._latest_invalid_reason
        elif not has_valid_sample:
            if self._latest_invalid_reason is not None:
                reason_code = self._latest_invalid_reason
            else:
                reason_code = (
                    "BATTERY_STARTUP_TIMEOUT"
                    if now - self._started_at >= self._startup_timeout_s
                    else "WAITING_FOR_FIRST_BATTERY_SAMPLE"
                )
        elif not telemetry_fresh:
            reason_code = "BATTERY_TELEMETRY_STALE"
        elif self._latest_invalid_reason is not None:
            reason_code = self._latest_invalid_reason
        else:
            reason_code = "BATTERY_SAMPLE_VALID"

        return BatteryObservation(
            percentage=self._percentage,
            present=self._present,
            power_supply_status=self._power_supply_status,
            measurement_valid=self._measurement_valid,
            has_valid_sample=has_valid_sample,
            telemetry_fresh=telemetry_fresh,
            reason_code=reason_code,
        )
