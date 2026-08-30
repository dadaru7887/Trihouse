"""영상 증거를 포함한 OMX 최종 파지 실패 보고의 인수 테스트."""

import unittest

from control_tower.task_manager.pick_failure_report import PickFailureReporter
from vision_ai.robot.media.recording.catalog import RecordingCatalog


class PickFailureReporterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = RecordingCatalog(capacity_bytes=1_000)
        self.catalog.start_segment('cam-1', 120, 100)
        self.reporter = PickFailureReporter(self.catalog)

    def test_final_failure_contains_traceable_work_and_recording_context(self) -> None:
        """UI can show the failed item and open the matching preconfigured camera segment."""
        report = self.reporter.report(
            job_id='job-1', order_id='order-1', item_id='item-1', shelf_id='S-01', slot_id='A-02',
            omx_id='OMX-01', camera_id='cam-1', occurred_at_s=149, last_result='gripper close timeout',
        )
        self.assertEqual('item-1', report.item_id)
        self.assertEqual('cam-1:120', report.recording_segment_id)
        self.assertEqual('recordings/cam-1/120.h264', report.recording_path)
        self.assertEqual('gripper close timeout', report.last_result)

    def test_other_items_can_continue_when_failure_isolated(self) -> None:
        """Only the failed item is held unless the caller declares the bundle blocked."""
        report = self.reporter.report(
            job_id='job-1', order_id='order-1', item_id='item-1', shelf_id='S-01', slot_id='A-02',
            omx_id='OMX-01', camera_id='cam-1', occurred_at_s=149, last_result='QR mismatch',
        )
        self.assertEqual('ITEM_HELD_CONTINUE_OTHERS', report.recommended_action)


if __name__ == '__main__':
    unittest.main()
