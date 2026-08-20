"""작업자·경로·OMX ROI 사람 이벤트의 인수 테스트.

쓰러짐 관련 test는 SR52 조사·승인 전에는 명시 실행 목록에 넣지 않는다.
"""

import unittest

from vision_system.person_worker.fall_monitor import MonitorConfig
from vision_system.person_worker.policy import BoundingBox, PersonObservation, PersonPolicy, PolygonRoi


class PersonPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.roi = PolygonRoi('packing-1', ((0, 0), (100, 0), (100, 100), (0, 100)))
        # FallMonitor 의 시간축: 자세 확정 1 초 -> 정지 지속 5 초 -> 확정 후보.
        self.policy = PersonPolicy(
            required_consecutive_frames=3,
            monitor=MonitorConfig(fall_confirm_seconds=1.0, immobile_seconds=5.0),
        )

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

    def test_fall_requires_low_posture_then_sustained_stillness(self) -> None:
        """움직이는 낮은 자세는 비상이 아니다. 지속되는 정지가 의심스럽다.

        FallMonitor 의 시간축을 그대로 따른다 — 자세가 `fall_confirm_seconds`
        만큼 유지되면 FALLEN, 거기서 정지가 `immobile_seconds` 만큼 이어지면
        확정 후보다. 두 단계로 나눈 이유는 "넘어졌다" 와 "넘어진 채 못 일어난다"
        가 다른 사건이기 때문이다. 사람이 부르는 것은 후자다.
        """
        self.assertIsNone(self.policy.observe_fall(self._person(timestamp_s=10, low_posture=True, moving=True)))
        self.assertIsNone(self.policy.observe_fall(self._person(timestamp_s=11, low_posture=True, moving=False)))
        self.assertIsNone(self.policy.observe_fall(self._person(timestamp_s=12, low_posture=True, moving=False)))
        self.assertIsNone(self.policy.observe_fall(self._person(timestamp_s=16.9, low_posture=True, moving=False)))
        event = self.policy.observe_fall(self._person(timestamp_s=17, low_posture=True, moving=False))
        self.assertIsNotNone(event)
        self.assertEqual('worker-7', event.track_id)

    def test_the_confirmation_request_is_sent_once(self) -> None:
        """같은 낙상으로 관제를 반복해서 부르면 사람이 무시하게 된다."""
        for timestamp in (10, 11, 12, 17):
            self.policy.observe_fall(self._person(timestamp_s=timestamp, low_posture=True, moving=False))
        self.assertIsNone(self.policy.observe_fall(self._person(timestamp_s=18, low_posture=True, moving=False)))

    def test_recovery_before_the_threshold_cancels_the_event(self) -> None:
        """의심 단계에서 일어나면 즉시 없던 일이 된다."""
        self.policy.observe_fall(self._person(timestamp_s=10, low_posture=True, moving=False))
        self.assertIsNone(self.policy.observe_fall(self._person(timestamp_s=13, low_posture=False, moving=True)))
        self.assertIsNone(self.policy.observe_fall(self._person(timestamp_s=18, low_posture=True, moving=False)))

    def test_one_noisy_frame_does_not_erase_accumulated_evidence(self) -> None:
        """segmentation 비율은 프레임마다 흔들린다. 한 프레임에 증거가 날아가면
        실제 낙상을 놓친다 — 2026-08-18 에 고친 리셋 비대칭 버그다."""
        for timestamp in (10, 11, 12):
            self.policy.observe_fall(self._person(timestamp_s=timestamp, low_posture=True, moving=False))
        self.assertEqual(
            'IMMOBILE',
            self.policy.fall_state(self._person(timestamp_s=13, low_posture=False, moving=False)),
        )

    def test_two_workers_do_not_share_fall_evidence(self) -> None:
        """한 사람이 일어났다고 다른 사람의 증거가 지워지면 안 된다."""
        for timestamp in (10, 11, 12):
            self.policy.observe_fall(self._person(timestamp_s=timestamp, low_posture=True, moving=False))
        other = PersonObservation('cam-1', 'worker-9', 12, BoundingBox(0, 0, 10, 10), 0.9, False, True)
        self.policy.observe_fall(other)
        self.assertEqual(
            'IMMOBILE',
            self.policy.fall_state(self._person(timestamp_s=13, low_posture=True, moving=False)),
        )


if __name__ == '__main__':
    unittest.main()
