"""작업자·경로·OMX ROI 사람 이벤트의 인수 테스트.

쓰러짐 관련 test는 SR52 조사·승인 전에는 명시 실행 목록에 넣지 않는다.
"""
from __future__ import annotations

import unittest

from vision_system.person_worker.policy import BoundingBox, PersonObservation, PersonPolicy, PolygonRoi


class PersonPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.roi = PolygonRoi('packing-1', ((0, 0), (100, 0), (100, 100), (0, 100)))
        self.policy = PersonPolicy(required_consecutive_frames=3, fall_static_for_s=5.0)

    def _person(self, *, timestamp_s: float, low_posture: bool = False, moving: bool = True) -> PersonObservation:
        return PersonObservation('cam-1', 'worker-7', timestamp_s, BoundingBox(20, 20, 40, 50), 0.9, low_posture, moving)

    def test_roi_requires_consecutive_person_frames(self) -> None:
        """One-frame detector noise must not block an OMX workspace or packing station."""
        self.assertFalse(self.policy.observe_roi(self._person(timestamp_s=1), self.roi).confirmed)
        self.assertFalse(self.policy.observe_roi(self._person(timestamp_s=2), self.roi).confirmed)
        event = self.policy.observe_roi(self._person(timestamp_s=3), self.roi)
        self.assertTrue(event.confirmed)
        self.assertEqual('packing-1', event.roi_id)

    def test_person_outside_roi_does_not_count_as_worker_presence(self) -> None:
        """People elsewhere in the camera image cannot reserve a packing station."""
        outside = PersonObservation('cam-1', 'worker-7', 1, BoundingBox(200, 200, 240, 240), 0.9, False, True)
        self.assertFalse(self.policy.observe_roi(outside, self.roi).overlaps_roi)

    def test_fall_requires_low_posture_and_static_duration(self) -> None:
        """A low but moving person is not an emergency; persistent stillness is suspicious."""
        self.assertIsNone(self.policy.observe_fall(self._person(timestamp_s=10, low_posture=True, moving=True)))
        self.assertIsNone(self.policy.observe_fall(self._person(timestamp_s=11, low_posture=True, moving=False)))
        self.assertIsNone(self.policy.observe_fall(self._person(timestamp_s=15.9, low_posture=True, moving=False)))
        event = self.policy.observe_fall(self._person(timestamp_s=16, low_posture=True, moving=False))
        self.assertIsNotNone(event)
        self.assertEqual('worker-7', event.track_id)

    def test_movement_or_recovered_posture_resets_fall_timer(self) -> None:
        """The event is cancelled when the person recovers before the threshold."""
        self.policy.observe_fall(self._person(timestamp_s=10, low_posture=True, moving=False))
        self.assertIsNone(self.policy.observe_fall(self._person(timestamp_s=13, low_posture=False, moving=True)))
        self.assertIsNone(self.policy.observe_fall(self._person(timestamp_s=18, low_posture=True, moving=False)))


if __name__ == '__main__':
    unittest.main()
