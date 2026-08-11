"""FMS 배차·예약·재할당 정책의 동작 테스트."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fleet_manager.dispatch_workflow import (  # noqa: E402
    DispatchWorkflow,
    PostTaskDirective,
    RobotSnapshot,
    TaskRequest,
)
from fleet_manager.battery_policy import BatteryPolicyState  # noqa: E402
from monitoring.measurement_log import MeasurementLogWriter  # noqa: E402


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

    def test_normal_robot_accepts_general_work(self) -> None:
        task = TaskRequest(
            'general', 1, 1, 'PACK-2', source_zone='AMBIENT', destination_zone='PACKING'
        )
        self.assertEqual('PK-02', self.fms.assign(task))

    def test_local_robot_accepts_only_frozen_packing_with_safe_rmf_soc(self) -> None:
        fms = DispatchWorkflow()
        fms.upsert_robot(
            RobotSnapshot(
                'PK-03', True, 18, 0, False,
                battery_state=BatteryPolicyState.LOCAL_ONLY,
            )
        )
        allowed = TaskRequest(
            'local', 1, 1, 'PACK-3',
            source_zone='FROZEN', destination_zone='PACKING',
            finish_state_of_charge=0.11,
        )
        self.assertEqual('PK-03', fms.assign(allowed))

    def test_final_local_job_returns_charge_directive_once_after_completion(self) -> None:
        fms = DispatchWorkflow()
        fms.upsert_robot(
            RobotSnapshot(
                'PK-03', True, 18, 0, False,
                battery_state=BatteryPolicyState.LOCAL_ONLY,
            )
        )
        task = TaskRequest(
            'last-local', 1, 1, 'PACK-4',
            source_zone='FROZEN', destination_zone='PACKING',
            finish_state_of_charge=0.051,
        )

        self.assertEqual('PK-03', fms.assign(task))
        self.assertEqual(
            PostTaskDirective(
                robot_id='PK-03',
                mode='RETURN_TO_CHARGE',
                reason_code='FINAL_LOCAL_JOB_COMPLETED',
            ),
            fms.complete('last-local'),
        )
        self.assertIsNone(fms.complete('last-local'))

    def test_local_robot_rejects_far_zone_low_soc_and_missing_estimate(self) -> None:
        for task in (
            TaskRequest('far', 1, 1, 'W1', source_zone='CHILLED', destination_zone='PACKING', finish_state_of_charge=0.5),
            TaskRequest('low', 1, 1, 'W2', source_zone='FROZEN', destination_zone='PACKING', finish_state_of_charge=0.05),
            TaskRequest('unknown', 1, 1, 'W3', source_zone='FROZEN', destination_zone='PACKING'),
        ):
            with self.subTest(task=task.job_id):
                fms = DispatchWorkflow()
                fms.upsert_robot(RobotSnapshot('PK-L', True, 18, 0, False, battery_state=BatteryPolicyState.LOCAL_ONLY))
                with self.assertRaisesRegex(ValueError, 'no assignable robot'):
                    fms.assign(task)

    def test_return_charge_and_recovery_states_are_excluded(self) -> None:
        for state in (
            BatteryPolicyState.RETURN_REQUIRED,
            BatteryPolicyState.CHARGE_WAIT,
            BatteryPolicyState.CHARGING,
            BatteryPolicyState.RECOVERY_CHECK,
            BatteryPolicyState.UNKNOWN,
        ):
            with self.subTest(state=state):
                fms = DispatchWorkflow()
                fms.upsert_robot(RobotSnapshot('PK-X', True, 80, 0, False, battery_state=state))
                with self.assertRaisesRegex(ValueError, 'no assignable robot'):
                    fms.assign(TaskRequest('job', 1, 1, 'W'))

    def test_records_the_policy_decision_used_for_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            writer = MeasurementLogWriter(
                root=directory, run_id="dispatch-test", component="control_tower"
            )
            fms = DispatchWorkflow(measurement_writer=writer)
            fms.upsert_robot(
                RobotSnapshot(
                    'PK-L', True, 18, 0, False,
                    battery_state=BatteryPolicyState.LOCAL_ONLY,
                )
            )
            task = TaskRequest(
                'local-job', 1, 1, 'PACK-9', source_zone='FROZEN',
                destination_zone='PACKING', finish_state_of_charge=0.11,
            )

            self.assertEqual('PK-L', fms.assign(task))

            records = [
                json.loads(line)
                for line in (
                    Path(directory)
                    / "dispatch-test"
                    / "battery_policy_decisions.jsonl"
                ).read_text().splitlines()
            ]
            selected = records[-1]
            self.assertEqual('local-job', selected['task_id'])
            self.assertEqual('PK-L', selected['robot_id'])
            self.assertEqual('LOCAL_ONLY', selected['state'])
            self.assertEqual('ALLOW_LOCAL_JOB', selected['action'])
            self.assertTrue(selected['selected'])


if __name__ == '__main__':
    unittest.main()
