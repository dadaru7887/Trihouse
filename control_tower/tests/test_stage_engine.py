"""멱등 FMS stage 전이의 인수 테스트."""
from __future__ import annotations

import unittest

from control_tower.task_manager.stage_engine import JobState, StageEngine


class StageEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = StageEngine()
        self.engine.create('job-1', stages=('PICK', 'LOAD', 'TRANSPORT', 'HANDOVER'))

    def test_matching_completion_advances_exactly_once(self) -> None:
        """A retry of the same robot completion never skips a stage."""
        self.assertTrue(self.engine.complete('job-1', stage_id='PICK', result_id='event-1'))
        self.assertFalse(self.engine.complete('job-1', stage_id='PICK', result_id='event-1'))
        self.assertEqual('LOAD', self.engine.current_stage('job-1'))

    def test_wrong_job_or_stage_completion_cannot_advance_workflow(self) -> None:
        """Stale results are recorded as invalid, not accepted as next-stage triggers."""
        self.assertFalse(self.engine.complete('job-1', stage_id='LOAD', result_id='event-2'))
        self.assertEqual('PICK', self.engine.current_stage('job-1'))

    def test_hold_then_resume_keeps_last_completed_step(self) -> None:
        """Resume continues the first unfinished stage rather than restarting the order."""
        self.engine.complete('job-1', stage_id='PICK', result_id='event-1')
        self.engine.hold('job-1', reason='operator check')
        self.assertEqual(JobState.HELD, self.engine.state_of('job-1'))
        self.engine.resume('job-1')
        self.assertEqual(JobState.RUNNING, self.engine.state_of('job-1'))
        self.assertEqual('LOAD', self.engine.current_stage('job-1'))

    def test_terminal_stage_marks_job_complete(self) -> None:
        """Only the final matching handover produces the overall completion state."""
        for index, stage in enumerate(('PICK', 'LOAD', 'TRANSPORT', 'HANDOVER')):
            self.assertTrue(self.engine.complete('job-1', stage_id=stage, result_id=f'event-{index}'))
        self.assertEqual(JobState.COMPLETED, self.engine.state_of('job-1'))
        self.assertIsNone(self.engine.current_stage('job-1'))


if __name__ == '__main__':
    unittest.main()
