"""검증된 배터리 관측으로 정책 state와 action을 각각 결정한다."""

from dataclasses import dataclass
from enum import StrEnum


POWER_SUPPLY_STATUS_CHARGING = 1


class BatteryPolicyState(StrEnum):
    UNKNOWN = "UNKNOWN"
    NORMAL = "NORMAL"
    LOCAL_ONLY = "LOCAL_ONLY"
    RETURN_REQUIRED = "RETURN_REQUIRED"
    CHARGE_WAIT = "CHARGE_WAIT"
    CHARGING = "CHARGING"
    RECOVERY_CHECK = "RECOVERY_CHECK"


class BatteryAction(StrEnum):
    NONE = "NONE"
    ALLOW_GENERAL_JOB = "ALLOW_GENERAL_JOB"
    ALLOW_LOCAL_JOB = "ALLOW_LOCAL_JOB"
    WAIT_AT_SAFE_NODE = "WAIT_AT_SAFE_NODE"
    COMPLETE_THEN_RETURN = "COMPLETE_THEN_RETURN"
    RETURN_TO_CHARGE = "RETURN_TO_CHARGE"
    HOLD_SAFE = "HOLD_SAFE"
    WAIT_FOR_CHARGE = "WAIT_FOR_CHARGE"
    REQUIRE_OPERATOR = "REQUIRE_OPERATOR"


@dataclass(frozen=True)
class BatteryConditionInput:
    percentage: float
    present: bool
    power_supply_status: int
    measurement_valid: bool
    has_valid_sample: bool
    telemetry_fresh: bool


@dataclass(frozen=True)
class BatteryPolicySnapshot:
    state: BatteryPolicyState
    ready: bool
    percentage: float
    reason_code: str
    detail: str = ""


@dataclass(frozen=True)
class WorkflowContext:
    source_zone: str = ""
    destination_zone: str = ""
    finish_state_of_charge: float | None = None
    has_cargo: bool = False
    handover_finish_soc: float | None = None
    charger_reachable: bool = True


@dataclass(frozen=True)
class BatteryActionDecision:
    action: BatteryAction
    reason_code: str
    detail: str = ""


def classify_condition(
    condition: BatteryConditionInput,
    *,
    recovery_check_required: bool = False,
    at_charger: bool = False,
    awaiting_reentry: bool = False,
) -> BatteryPolicySnapshot:
    """우선순위에 따라 하나의 현재 정책 state를 계산한다."""

    if not (
        condition.present
        and condition.measurement_valid
        and condition.has_valid_sample
        and condition.telemetry_fresh
        and 0.0 <= condition.percentage <= 100.0
    ):
        return BatteryPolicySnapshot(
            BatteryPolicyState.UNKNOWN,
            False,
            condition.percentage,
            _unknown_reason(condition),
        )
    if recovery_check_required:
        return BatteryPolicySnapshot(
            BatteryPolicyState.RECOVERY_CHECK,
            False,
            condition.percentage,
            "RECOVERY_CHECK_REQUIRED",
        )
    if condition.power_supply_status == POWER_SUPPLY_STATUS_CHARGING:
        return BatteryPolicySnapshot(
            BatteryPolicyState.CHARGING,
            False,
            condition.percentage,
            "BATTERY_CHARGING",
        )
    if at_charger or (awaiting_reentry and condition.percentage < 30.0):
        return BatteryPolicySnapshot(
            BatteryPolicyState.CHARGE_WAIT,
            False,
            condition.percentage,
            "WAITING_FOR_CHARGE_OR_REENTRY_LEVEL",
        )
    if awaiting_reentry and condition.percentage >= 30.0:
        return BatteryPolicySnapshot(
            BatteryPolicyState.NORMAL,
            True,
            condition.percentage,
            "REENTRY_THRESHOLD_REACHED",
        )
    if condition.percentage <= 10.0:
        return BatteryPolicySnapshot(
            BatteryPolicyState.RETURN_REQUIRED,
            False,
            condition.percentage,
            "BATTERY_AT_OR_BELOW_RETURN_THRESHOLD",
        )
    if condition.percentage <= 20.0:
        return BatteryPolicySnapshot(
            BatteryPolicyState.LOCAL_ONLY,
            True,
            condition.percentage,
            "BATTERY_LOCAL_WORK_ONLY",
        )
    return BatteryPolicySnapshot(
        BatteryPolicyState.NORMAL,
        True,
        condition.percentage,
        "BATTERY_NORMAL",
    )


def decide_action(
    snapshot: BatteryPolicySnapshot,
    workflow: WorkflowContext,
    *,
    hard_stop_percent: float = 5.0,
    handover_reserve_soc: float = 0.03,
) -> BatteryActionDecision:
    """state와 작업 맥락을 이용해 실행 계층에 전달할 행동을 선택한다."""

    if snapshot.state in (BatteryPolicyState.UNKNOWN, BatteryPolicyState.RECOVERY_CHECK):
        return BatteryActionDecision(BatteryAction.HOLD_SAFE, snapshot.reason_code)
    if snapshot.state == BatteryPolicyState.CHARGING:
        return BatteryActionDecision(BatteryAction.WAIT_FOR_CHARGE, "CHARGING_IN_PROGRESS")
    if snapshot.state == BatteryPolicyState.CHARGE_WAIT:
        return BatteryActionDecision(BatteryAction.HOLD_SAFE, "WAITING_FOR_CHARGE")
    if snapshot.state == BatteryPolicyState.NORMAL:
        return BatteryActionDecision(BatteryAction.ALLOW_GENERAL_JOB, "GENERAL_JOB_ALLOWED")
    if snapshot.state == BatteryPolicyState.LOCAL_ONLY:
        local_route = {
            workflow.source_zone.upper(),
            workflow.destination_zone.upper(),
        } == {"FROZEN", "PACKING"}
        if not local_route:
            return BatteryActionDecision(BatteryAction.WAIT_AT_SAFE_NODE, "LOCAL_ROUTE_REQUIRED")
        if workflow.finish_state_of_charge is None:
            return BatteryActionDecision(
                BatteryAction.WAIT_AT_SAFE_NODE,
                "RMF_ENERGY_ESTIMATE_UNAVAILABLE",
            )
        if workflow.finish_state_of_charge > 0.10:
            return BatteryActionDecision(BatteryAction.ALLOW_LOCAL_JOB, "LOCAL_JOB_ALLOWED")
        if workflow.finish_state_of_charge > hard_stop_percent / 100.0:
            return BatteryActionDecision(
                BatteryAction.COMPLETE_THEN_RETURN,
                "FINAL_LOCAL_JOB_THEN_CHARGE",
            )
        return BatteryActionDecision(
            BatteryAction.RETURN_TO_CHARGE,
            "PREDICTED_FINISH_SOC_AT_HARD_STOP",
        )

    if not workflow.has_cargo:
        return BatteryActionDecision(BatteryAction.RETURN_TO_CHARGE, "RETURN_THRESHOLD_REACHED")
    if snapshot.percentage < hard_stop_percent:
        return BatteryActionDecision(BatteryAction.REQUIRE_OPERATOR, "BATTERY_BELOW_HARD_STOP")
    if workflow.handover_finish_soc is None:
        return BatteryActionDecision(
            BatteryAction.REQUIRE_OPERATOR,
            "HANDOVER_ENERGY_ESTIMATE_UNAVAILABLE",
        )
    if workflow.handover_finish_soc < handover_reserve_soc:
        return BatteryActionDecision(BatteryAction.REQUIRE_OPERATOR, "HANDOVER_RESERVE_UNSAFE")
    if not workflow.charger_reachable:
        return BatteryActionDecision(BatteryAction.REQUIRE_OPERATOR, "CHARGER_UNREACHABLE_AFTER_HANDOVER")
    return BatteryActionDecision(BatteryAction.COMPLETE_THEN_RETURN, "SAFE_HANDOVER_THEN_RETURN")


def _unknown_reason(condition: BatteryConditionInput) -> str:
    if not condition.present:
        return "BATTERY_NOT_PRESENT"
    if not condition.measurement_valid:
        return "BATTERY_PERCENTAGE_INVALID"
    if not condition.has_valid_sample:
        return "WAITING_FOR_FIRST_BATTERY_SAMPLE"
    if not condition.telemetry_fresh:
        return "BATTERY_TELEMETRY_STALE"
    return "BATTERY_PERCENTAGE_INVALID"
