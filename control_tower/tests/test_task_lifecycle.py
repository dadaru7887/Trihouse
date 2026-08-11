"""관리자 개입과 비상 보류의 인수 테스트."""

import unittest

from control_tower.task_manager.lifecycle import TaskLifecycle, TaskState


class TaskLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = TaskLifecycle()
        self.tasks.create('job-1', order_id='order-1', robot_id='PK-01')

    def test_cancel_is_confirmed_and_idempotent(self) -> None:
        """A repeated confirmed action has one effect; an unconfirmed one has none."""
        self.assertEqual(TaskState.QUEUED, self.tasks.cancel('job-1', request_id='cancel-1', confirmed=False).state)
        first = self.tasks.cancel('job-1', request_id='cancel-1', confirmed=True)
        second = self.tasks.cancel('job-1', request_id='cancel-1', confirmed=True)
        self.assertEqual(TaskState.CANCELLED, first.state)
        self.assertEqual(first, second)

    def test_hold_preserves_cargo_and_completed_stages(self) -> None:
        """An interrupted loaded robot is held, not reset or silently reassigned."""
        self.tasks.complete_step('job-1', 'PICKED')
        self.tasks.complete_step('job-1', 'LOADED')
        held = self.tasks.hold('job-1', reason='emergency', cargo_present=True)
        self.assertEqual(TaskState.ADMIN_INTERVENTION_REQUIRED, held.state)
        self.assertEqual(('PICKED', 'LOADED'), held.completed_steps)

    def test_reassign_continues_after_last_completed_stage(self) -> None:
        """A safe reassignment continues transport rather than repeating pickup/load."""
        self.tasks.complete_step('job-1', 'PICKED')
        self.tasks.complete_step('job-1', 'LOADED')
        held = self.tasks.hold('job-1', reason='robot unavailable', cargo_present=False)
        reassigned = self.tasks.reassign('job-1', request_id='reassign-1', confirmed=True, robot_id='PK-02')
        self.assertEqual(TaskState.ASSIGNED, reassigned.state)
        self.assertEqual('TRANSPORT', reassigned.next_step)
        self.assertEqual('PK-02', reassigned.robot_id)

    def test_emergency_clear_does_not_resume_interrupted_task(self) -> None:
        """Release only removes the zone hold; FMS needs a fresh assignment decision."""
        self.tasks.hold('job-1', reason='emergency', cargo_present=False)
        released = self.tasks.release_emergency_hold('job-1', event_id='emg-1', approved_by='admin-1')
        self.assertEqual(TaskState.HELD, released.state)
        self.assertEqual('fresh FMS assignment required', released.reason)


if __name__ == '__main__':
    unittest.main()
