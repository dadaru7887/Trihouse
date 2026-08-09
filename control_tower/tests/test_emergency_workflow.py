"""FMS 비상 구역과 해제 후 복귀 인수인계의 인수 테스트."""
from __future__ import annotations

import unittest

from control_tower.task_manager.emergency_workflow import EmergencyWorkflow, RecoveryAction


class EmergencyWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = EmergencyWorkflow()
        self.workflow.open('incident-1', polygon=((0, 0), (4, 0), (4, 4), (0, 4)))

    def test_zone_blocks_new_assignments_only_inside_affected_area(self) -> None:
        """FMS denies a target inside the incident zone without grounding the whole fleet."""
        self.assertTrue(self.workflow.blocks_assignment('incident-1', target_xy=(2, 2)))
        self.assertFalse(self.workflow.blocks_assignment('incident-1', target_xy=(5, 2)))

    def test_affected_empty_robot_is_held_and_returned_after_approval(self) -> None:
        """Release does not resume the interrupted job; it schedules return and health check."""
        self.workflow.affect_robot('incident-1', robot_id='PK-01', job_id='job-1', cargo_present=False)
        action = self.workflow.release('incident-1', operator_id='admin-1')
        self.assertEqual((RecoveryAction('PK-01', 'RETURN_AND_HEALTH_CHECK', 'job-1'),), action)
        self.assertFalse(self.workflow.blocks_assignment('incident-1', target_xy=(2, 2)))

    def test_loaded_robot_requires_administrator_intervention_after_release(self) -> None:
        """FMS never auto-reassigns cargo whose physical state cannot be transferred safely."""
        self.workflow.affect_robot('incident-1', robot_id='PK-02', job_id='job-2', cargo_present=True)
        action = self.workflow.release('incident-1', operator_id='admin-1')
        self.assertEqual((RecoveryAction('PK-02', 'ADMIN_INTERVENTION_REQUIRED', 'job-2'),), action)

    def test_release_requires_an_identified_operator(self) -> None:
        """A detection clear signal cannot remove the controlled emergency zone."""
        with self.assertRaises(ValueError):
            self.workflow.release('incident-1', operator_id='')


if __name__ == '__main__':
    unittest.main()
