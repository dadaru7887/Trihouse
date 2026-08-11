"""Pinky 복귀·보류 배터리 판단의 인수 테스트."""

import unittest

from control_tower.fleet_manager.battery_policy import BatteryDecision, BatteryPolicy, BatteryStatus


class BatteryPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = BatteryPolicy(return_threshold_percent=20, emergency_threshold_percent=10, consumption_percent_per_m=1.0, safety_margin_percent=5.0)

    def test_healthy_battery_keeps_current_and_next_assignment_available(self) -> None:
        """A robot with enough predicted energy is not sent away unnecessarily."""
        decision = self.policy.decide(battery_percent=70, remaining_current_m=10, return_to_charge_m=10, has_cargo=False)
        self.assertEqual(BatteryDecision.CONTINUE, decision)

    def test_insufficient_energy_for_current_and_return_holds_new_work_then_returns(self) -> None:
        """FMS must not create a new commitment when finishing and returning is unsafe."""
        decision = self.policy.decide(battery_percent=25, remaining_current_m=15, return_to_charge_m=10, has_cargo=False)
        self.assertEqual(BatteryDecision.HOLD_CURRENT_AND_RETURN, decision)

    def test_existing_cargo_finishes_before_return_when_energy_is_sufficient(self) -> None:
        """A loaded Pinky completes the safe delivery before a normal charge return."""
        decision = self.policy.decide(battery_percent=24, remaining_current_m=8, return_to_charge_m=8, has_cargo=True)
        self.assertEqual(BatteryDecision.COMPLETE_THEN_RETURN, decision)

    def test_emergency_threshold_rejects_new_work_even_without_route_estimate(self) -> None:
        """Below the emergency threshold, the robot is unavailable for any new task."""
        decision = self.policy.decide(battery_percent=9, remaining_current_m=0, return_to_charge_m=2, has_cargo=False)
        self.assertEqual(BatteryDecision.IMMEDIATE_RETURN, decision)

    def test_status_classifies_normal_limited_and_return_required(self) -> None:
        """Dispatch can visibly distinguish a short-task-only robot from one that must return."""
        self.assertEqual(BatteryStatus.NORMAL, self.policy.status(70))
        self.assertEqual(BatteryStatus.WORK_LIMITED, self.policy.status(18))
        self.assertEqual(BatteryStatus.RETURN_REQUIRED, self.policy.status(9))

    def test_work_limited_robot_accepts_only_route_that_preserves_return_margin(self) -> None:
        """A low battery robot may take a short nearby task, never a long commitment."""
        self.assertTrue(self.policy.can_accept_new_job(battery_percent=18, job_distance_m=4, return_to_charge_m=6))
        self.assertFalse(self.policy.can_accept_new_job(battery_percent=18, job_distance_m=9, return_to_charge_m=6))


if __name__ == '__main__':
    unittest.main()
