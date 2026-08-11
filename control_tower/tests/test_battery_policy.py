"""Control Tower 배터리 state 분류와 action 결정 테스트."""

import unittest

from control_tower.fleet_manager.battery_policy import (
    BatteryAction,
    BatteryConditionInput,
    BatteryPolicyState,
    WorkflowContext,
    classify_condition,
    decide_action,
)


def condition(percentage: float, *, status: int = 2) -> BatteryConditionInput:
    return BatteryConditionInput(
        percentage=percentage,
        present=True,
        power_supply_status=status,
        measurement_valid=True,
        has_valid_sample=True,
        telemetry_fresh=True,
    )


class BatteryStateTest(unittest.TestCase):
    def test_percentage_boundaries(self) -> None:
        self.assertEqual(BatteryPolicyState.NORMAL, classify_condition(condition(20.1)).state)
        self.assertEqual(BatteryPolicyState.LOCAL_ONLY, classify_condition(condition(20.0)).state)
        self.assertEqual(BatteryPolicyState.LOCAL_ONLY, classify_condition(condition(10.1)).state)
        self.assertEqual(BatteryPolicyState.RETURN_REQUIRED, classify_condition(condition(10.0)).state)

    def test_unknown_has_highest_priority(self) -> None:
        unavailable = BatteryConditionInput(80, True, 1, True, True, False)
        result = classify_condition(
            unavailable, at_charger=True, recovery_check_required=True
        )
        self.assertEqual(BatteryPolicyState.UNKNOWN, result.state)
        self.assertFalse(result.ready)

    def test_absent_and_invalid_measurements_keep_specific_reason_codes(self) -> None:
        absent = classify_condition(BatteryConditionInput(0, False, 0, False, False, False))
        invalid = classify_condition(BatteryConditionInput(0, True, 0, False, False, False))
        self.assertEqual("BATTERY_NOT_PRESENT", absent.reason_code)
        self.assertEqual("BATTERY_PERCENTAGE_INVALID", invalid.reason_code)

    def test_recovery_charging_and_charge_wait_priorities(self) -> None:
        self.assertEqual(
            BatteryPolicyState.RECOVERY_CHECK,
            classify_condition(condition(80, status=1), recovery_check_required=True).state,
        )
        self.assertEqual(
            BatteryPolicyState.CHARGING,
            classify_condition(condition(18, status=1)).state,
        )
        self.assertEqual(
            BatteryPolicyState.CHARGE_WAIT,
            classify_condition(condition(18), at_charger=True).state,
        )

    def test_charge_or_recovery_releases_only_at_thirty_percent(self) -> None:
        self.assertEqual(
            BatteryPolicyState.CHARGE_WAIT,
            classify_condition(condition(29.9), awaiting_reentry=True).state,
        )
        self.assertEqual(
            BatteryPolicyState.NORMAL,
            classify_condition(condition(30.0), awaiting_reentry=True).state,
        )


class BatteryActionTest(unittest.TestCase):
    def test_normal_allows_general_job(self) -> None:
        decision = decide_action(
            classify_condition(condition(80)),
            WorkflowContext(source_zone="AMBIENT", destination_zone="PACKING"),
        )
        self.assertEqual(BatteryAction.ALLOW_GENERAL_JOB, decision.action)

    def test_local_only_allows_continuing_cycle_above_ten_percent(self) -> None:
        snapshot = classify_condition(condition(18))
        allowed = decide_action(
            snapshot,
            WorkflowContext("FROZEN", "PACKING", finish_state_of_charge=0.101),
        )
        self.assertEqual(BatteryAction.ALLOW_LOCAL_JOB, allowed.action)

    def test_local_only_accepts_one_final_job_above_five_percent(self) -> None:
        snapshot = classify_condition(condition(18))
        decision = decide_action(
            snapshot,
            WorkflowContext("FROZEN", "PACKING", finish_state_of_charge=0.051),
        )
        self.assertEqual(BatteryAction.COMPLETE_THEN_RETURN, decision.action)
        self.assertEqual("FINAL_LOCAL_JOB_THEN_CHARGE", decision.reason_code)

    def test_local_only_returns_immediately_at_hard_stop_prediction(self) -> None:
        snapshot = classify_condition(condition(18))
        decision = decide_action(
            snapshot,
            WorkflowContext("FROZEN", "PACKING", finish_state_of_charge=0.05),
        )
        self.assertEqual(BatteryAction.RETURN_TO_CHARGE, decision.action)
        self.assertEqual("PREDICTED_FINISH_SOC_AT_HARD_STOP", decision.reason_code)

    def test_local_only_rejects_other_zones_and_missing_estimate(self) -> None:
        snapshot = classify_condition(condition(18))
        rejected_zone = decide_action(
            snapshot,
            WorkflowContext("CHILLED", "PACKING", finish_state_of_charge=0.5),
        )
        missing_estimate = decide_action(
            snapshot, WorkflowContext("FROZEN", "PACKING")
        )
        self.assertEqual(BatteryAction.WAIT_AT_SAFE_NODE, rejected_zone.action)
        self.assertEqual(BatteryAction.WAIT_AT_SAFE_NODE, missing_estimate.action)

    def test_return_required_without_cargo_returns_to_charge(self) -> None:
        decision = decide_action(
            classify_condition(condition(10)), WorkflowContext(has_cargo=False)
        )
        self.assertEqual(BatteryAction.RETURN_TO_CHARGE, decision.action)

    def test_loaded_robot_completes_only_above_hard_stop_and_reserve(self) -> None:
        snapshot = classify_condition(condition(8))
        complete = decide_action(
            snapshot,
            WorkflowContext(has_cargo=True, handover_finish_soc=0.03),
        )
        unsafe_finish = decide_action(
            snapshot,
            WorkflowContext(has_cargo=True, handover_finish_soc=0.029),
        )
        hard_stop = decide_action(
            classify_condition(condition(4.9)),
            WorkflowContext(has_cargo=True, handover_finish_soc=0.5),
        )
        self.assertEqual(BatteryAction.COMPLETE_THEN_RETURN, complete.action)
        self.assertEqual(BatteryAction.REQUIRE_OPERATOR, unsafe_finish.action)
        self.assertEqual(BatteryAction.REQUIRE_OPERATOR, hard_stop.action)

    def test_charging_and_unknown_never_accept_work(self) -> None:
        charging = decide_action(
            classify_condition(condition(50, status=1)), WorkflowContext()
        )
        unknown_condition = BatteryConditionInput(0, False, 0, False, False, False)
        unknown = decide_action(classify_condition(unknown_condition), WorkflowContext())
        self.assertEqual(BatteryAction.WAIT_FOR_CHARGE, charging.action)
        self.assertEqual(BatteryAction.HOLD_SAFE, unknown.action)


if __name__ == "__main__":
    unittest.main()
