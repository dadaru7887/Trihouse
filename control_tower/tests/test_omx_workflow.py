"""OMX 파지·정지·임시 적재·인수인계 규칙의 인수 테스트."""
from __future__ import annotations

import unittest

from control_tower.task_manager.omx_workflow import OmxState, OmxWorkflow


class OmxWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.omx = OmxWorkflow(retry_offsets=((0.0, 0.0), (0.01, 0.0), (-0.01, 0.0)))
        self.omx.start('job-1', order_id='order-1', expected_items=('item-1', 'item-2'))

    def test_qr_or_marker_failure_never_starts_a_pick(self) -> None:
        """The arm receives no pick motion until both identity and pose checks pass."""
        result = self.omx.authorize_pick('job-1', 'item-1', qr_matches=False, marker_valid=True)
        self.assertFalse(result.accepted)
        self.assertEqual(OmxState.RECOGNITION_REQUIRED, result.state)

    def test_pick_retry_uses_registered_offsets_then_holds_the_item(self) -> None:
        """Each failed pick re-observes and changes offset; retries stop at the configured bound."""
        self.omx.authorize_pick('job-1', 'item-1', qr_matches=True, marker_valid=True)
        self.assertEqual((0.01, 0.0), self.omx.pick_failed('job-1', 'item-1').next_offset)
        self.omx.authorize_pick('job-1', 'item-1', qr_matches=True, marker_valid=True)
        self.assertEqual((-0.01, 0.0), self.omx.pick_failed('job-1', 'item-1').next_offset)
        self.omx.authorize_pick('job-1', 'item-1', qr_matches=True, marker_valid=True)
        final = self.omx.pick_failed('job-1', 'item-1')
        self.assertEqual(OmxState.ITEM_HELD, final.state)
        self.assertEqual('pick retry exhausted', final.reason)

    def test_two_items_reserve_distinct_temporary_slots(self) -> None:
        """Prepared multi-item stock cannot be mixed with another job's temporary inventory."""
        self.assertEqual('TMP-01', self.omx.reserve_temporary_slot('job-1', 'item-1', ('TMP-01', 'TMP-02')))
        self.assertEqual('TMP-02', self.omx.reserve_temporary_slot('job-1', 'item-2', ('TMP-01', 'TMP-02')))
        self.omx.start('job-2', order_id='order-2', expected_items=('item-3',))
        with self.assertRaises(ValueError):
            self.omx.reserve_temporary_slot('job-2', 'item-3', ('TMP-01', 'TMP-02'))

    def test_cancel_releases_temporary_slots_for_a_later_job(self) -> None:
        """A held or cancelled job cannot leak scarce temporary shelf capacity."""
        self.omx.reserve_temporary_slot('job-1', 'item-1', ('TMP-01',))
        self.omx.cancel('job-1')
        self.omx.start('job-2', order_id='order-2', expected_items=('item-3',))
        self.assertEqual('TMP-01', self.omx.reserve_temporary_slot('job-2', 'item-3', ('TMP-01',)))

    def test_person_pause_blocks_new_motion_and_resume_keeps_completed_steps(self) -> None:
        """A held item is not dropped or picked again after a person-safety pause."""
        self.omx.authorize_pick('job-1', 'item-1', qr_matches=True, marker_valid=True)
        self.omx.pick_succeeded('job-1', 'item-1')
        self.omx.person_entered('job-1')
        self.assertEqual(OmxState.PAUSED_FOR_PERSON, self.omx.state_of('job-1'))
        self.assertFalse(self.omx.authorize_pick('job-1', 'item-2', qr_matches=True, marker_valid=True).accepted)
        self.omx.person_cleared('job-1', consecutive_safe_frames=True)
        self.assertEqual(OmxState.READY_TO_LOAD, self.omx.state_of('job-1'))

    def test_handover_requires_all_expected_items_and_safe_retreat(self) -> None:
        """Pinky cannot depart on a partial or mechanically incomplete OMX load."""
        self.assertFalse(self.omx.confirm_handover('job-1', loaded_items=('item-1',), gripper_open=True, retreated=True).accepted)
        self.assertFalse(self.omx.confirm_handover('job-1', loaded_items=('item-1', 'item-2'), gripper_open=False, retreated=True).accepted)
        accepted = self.omx.confirm_handover('job-1', loaded_items=('item-1', 'item-2'), gripper_open=True, retreated=True)
        self.assertTrue(accepted.accepted)
        self.assertEqual(OmxState.HANDOVER_CONFIRMED, accepted.state)


if __name__ == '__main__':
    unittest.main()
