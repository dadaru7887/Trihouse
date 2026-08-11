"""카메라 segment 보존과 증거 조회의 인수 테스트."""

import unittest

from vision_system.recording_server.catalog import RecordingCatalog, SegmentState


class RecordingCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = RecordingCatalog(capacity_bytes=300)

    def test_segments_are_camera_and_minute_addressable(self) -> None:
        """UI evidence lookup identifies one camera's exact one-minute file."""
        segment = self.catalog.start_segment('cam-1', minute_start_s=120, size_bytes=100)
        self.catalog.complete(segment.segment_id)
        found = self.catalog.lookup('cam-1', timestamp_s=179)
        self.assertEqual(segment.segment_id, found.segment_id)
        self.assertEqual('cam-1', found.camera_id)

    def test_eviction_uses_oldest_completed_not_recording_or_playing_segment(self) -> None:
        """Retention may remove only finished, non-replayed evidence."""
        self.catalog = RecordingCatalog(capacity_bytes=250)
        old = self.catalog.start_segment('cam-1', 0, 100); self.catalog.complete(old.segment_id)
        protected = self.catalog.start_segment('cam-1', 60, 100); self.catalog.complete(protected.segment_id)
        self.catalog.set_playing(protected.segment_id, True)
        active = self.catalog.start_segment('cam-2', 120, 100)
        self.catalog.enforce_retention()
        self.assertIsNone(self.catalog.get(old.segment_id))
        self.assertEqual(SegmentState.COMPLETE, self.catalog.get(protected.segment_id).state)
        self.assertEqual(SegmentState.RECORDING, self.catalog.get(active.segment_id).state)

    def test_retention_does_not_delete_when_only_protected_files_remain(self) -> None:
        """Capacity pressure cannot destroy active recording or operator playback."""
        playing = self.catalog.start_segment('cam-1', 0, 200); self.catalog.complete(playing.segment_id); self.catalog.set_playing(playing.segment_id, True)
        active = self.catalog.start_segment('cam-2', 60, 200)
        self.assertEqual((), self.catalog.enforce_retention())
        self.assertIsNotNone(self.catalog.get(playing.segment_id))
        self.assertIsNotNone(self.catalog.get(active.segment_id))


if __name__ == '__main__':
    unittest.main()
