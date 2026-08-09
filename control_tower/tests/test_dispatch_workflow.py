"""FMS 배차·예약·재할당 정책의 동작 테스트."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fleet_manager.dispatch_workflow import DispatchWorkflow, RobotSnapshot, TaskRequest  # noqa: E402


class DispatchWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fms = DispatchWorkflow()
        self.fms.upsert_robot(RobotSnapshot('PK-01', ready=True, battery=80, available_at_s=30, cargo_present=False))
        self.fms.upsert_robot(RobotSnapshot('PK-02', ready=True, battery=80, available_at_s=5, cargo_present=False))

    def test_high_priority_task_claims_shared_packing_station_first(self) -> None:
        """A packing station cannot be assigned twice; priority then request order decides."""
        urgent = TaskRequest('job-urgent', priority=2, requested_at_s=2, workspace_id='PACK-1')
        normal = TaskRequest('job-normal', priority=1, requested_at_s=1, workspace_id='PACK-1')
        self.assertEqual('PK-02', self.fms.assign(urgent))
        with self.assertRaises(ValueError):
            self.fms.assign(normal)

    def test_scheduler_orders_priority_before_request_time(self) -> None:
        """An urgent request queued later outranks a normal request for the same resource."""
        scheduled = self.fms.schedule([
            TaskRequest('job-normal', priority=1, requested_at_s=1, workspace_id='PACK-1'),
            TaskRequest('job-urgent', priority=2, requested_at_s=2, workspace_id='PACK-1'),
        ])
        self.assertEqual(('job-urgent',), tuple(scheduled))

    def test_reassignment_keeps_next_unfinished_step_when_cargo_is_not_on_robot(self) -> None:
        """A replacement Pinky must not repeat a completed pick/load stage."""
        task = TaskRequest('job-1', priority=1, requested_at_s=1, workspace_id='OMX-1', completed_steps=('PICKED', 'LOADED'))
        self.assertEqual('PK-02', self.fms.assign(task))
        reassigned = self.fms.reassign('job-1', failed_robot_id='PK-02', cargo_present=False)
        self.assertEqual('PK-01', reassigned.robot_id)
        self.assertEqual('TRANSPORT', reassigned.next_step)

    def test_cargo_on_failed_robot_requires_manual_intervention(self) -> None:
        """A task with cargo left on an unavailable Pinky must not be auto-reassigned."""
        task = TaskRequest('job-1', priority=1, requested_at_s=1, workspace_id='OMX-1')
        self.fms.assign(task)
        result = self.fms.reassign('job-1', failed_robot_id='PK-02', cargo_present=True)
        self.assertFalse(result.assigned)
        self.assertEqual('MANUAL_INTERVENTION', result.next_step)

    def test_cancelling_task_releases_workspace_for_next_task(self) -> None:
        """A reservation survives until cancellation or a completion event releases it."""
        self.fms.assign(TaskRequest('job-1', priority=1, requested_at_s=1, workspace_id='PACK-1'))
        self.fms.cancel('job-1')
        self.assertEqual('PK-02', self.fms.assign(TaskRequest('job-2', priority=1, requested_at_s=2, workspace_id='PACK-1')))


if __name__ == '__main__':
    unittest.main()
