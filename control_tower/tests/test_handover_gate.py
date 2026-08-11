"""Pinky·OMX 인수인계 준비 상태 동기화의 인수 테스트."""

import unittest

from control_tower.task_manager.handover_gate import HandoverGate


class HandoverGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = HandoverGate()
        self.gate.expect('job-1', pinky_id='PK-01', omx_id='OMX-01')

    def test_start_is_denied_until_both_matching_readiness_events_arrive(self) -> None:
        """One robot waiting safely does not authorize the other to load/unload."""
        self.assertFalse(self.gate.mark_ready('job-1', robot_id='PK-01', role='PINKY'))
        self.assertFalse(self.gate.can_start('job-1'))
        self.assertTrue(self.gate.mark_ready('job-1', robot_id='OMX-01', role='OMX'))
        self.assertTrue(self.gate.can_start('job-1'))

    def test_wrong_robot_or_role_cannot_unlock_handover(self) -> None:
        """Stale/foreign state messages never authorize a different pairing."""
        self.assertFalse(self.gate.mark_ready('job-1', robot_id='PK-02', role='PINKY'))
        self.assertFalse(self.gate.mark_ready('job-1', robot_id='PK-01', role='OMX'))
        self.assertFalse(self.gate.can_start('job-1'))

    def test_cancel_or_reassignment_invalidates_old_readiness(self) -> None:
        """A previous Pinky's ready event cannot survive a target robot change."""
        self.gate.mark_ready('job-1', robot_id='PK-01', role='PINKY')
        self.gate.mark_ready('job-1', robot_id='OMX-01', role='OMX')
        self.assertTrue(self.gate.can_start('job-1'))
        self.gate.reassign_pinky('job-1', pinky_id='PK-02')
        self.assertFalse(self.gate.can_start('job-1'))
        self.gate.mark_ready('job-1', robot_id='PK-02', role='PINKY')
        self.gate.mark_ready('job-1', robot_id='OMX-01', role='OMX')
        self.assertTrue(self.gate.can_start('job-1'))


if __name__ == '__main__':
    unittest.main()
