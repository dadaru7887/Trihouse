"""OMX 동작 전 QR 물품 ID·ArUco 선반 확인의 인수 테스트."""

import unittest

from vision_ai.robot.marker.policy import MarkerObservation, MarkerPolicy, PickAuthorization, QrObservation


class MarkerPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = MarkerPolicy(max_translation_error_m=0.03, max_rotation_error_deg=5.0)
        self.authorization = PickAuthorization('job-1', 'order-1', 'item-1', 'shelf-A', 'slot-2')

    def test_qr_must_match_the_reserved_order_and_item(self) -> None:
        """A visible but different product never authorizes a grasp."""
        accepted = self.policy.verify_qr(self.authorization, QrObservation('item-1', 'order-1'))
        rejected = self.policy.verify_qr(self.authorization, QrObservation('item-2', 'order-1'))
        self.assertTrue(accepted.approved)
        self.assertFalse(rejected.approved)
        self.assertEqual('item mismatch', rejected.reason)

    def test_missing_or_wrong_aruco_marker_blocks_motion(self) -> None:
        """No marker correction means the arm must re-observe rather than move blind."""
        wrong = MarkerObservation('shelf-B', translation_error_m=0.0, rotation_error_deg=0.0)
        self.assertFalse(self.policy.verify_marker(self.authorization, wrong).approved)
        self.assertFalse(self.policy.verify_marker(self.authorization, None).approved)

    def test_marker_pose_outside_registered_tolerance_blocks_motion(self) -> None:
        """A large shelf-pose error triggers re-recognition, not an unbounded correction."""
        excessive = MarkerObservation('shelf-A', translation_error_m=0.04, rotation_error_deg=2.0)
        result = self.policy.verify_marker(self.authorization, excessive)
        self.assertFalse(result.approved)
        self.assertEqual('translation tolerance exceeded', result.reason)


if __name__ == '__main__':
    unittest.main()
