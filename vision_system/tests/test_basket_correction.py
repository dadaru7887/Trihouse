"""OMX 적재 전 Pinky 바구니 pose 보정의 인수 테스트."""

import unittest

from vision_system.object_worker.basket_correction import BasketCorrectionPolicy, BasketObservation, Pose2D


class BasketCorrectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = BasketCorrectionPolicy(max_translation_m=0.05, max_rotation_deg=5.0)

    def test_applies_translation_and_rotation_to_registered_load_point(self) -> None:
        """The registered empty-basket point moves with the observed basket pose."""
        result = self.policy.correct(Pose2D(1.0, 2.0, 0.0), BasketObservation(((0, 0), (2, 0), (2, 2), (0, 2)), translation_m=(0.01, 0.0), rotation_deg=0.0))
        self.assertTrue(result.approved)
        self.assertEqual(Pose2D(1.01, 2.0, 0.0), result.corrected_pose)

    def test_unstable_or_excessive_basket_pose_requests_pinky_reposition(self) -> None:
        """OMX never compensates a large or incomplete basket observation on its own."""
        result = self.policy.correct(Pose2D(1.0, 2.0, 0.0), BasketObservation(((0, 0), (2, 0), (2, 2)), translation_m=(0.1, 0.0), rotation_deg=0.0))
        self.assertFalse(result.approved)
        self.assertEqual('REQUEST_PINKY_REPOSITION', result.action)

    def test_rotation_beyond_limit_requests_pinky_reposition(self) -> None:
        """Pose correction is bounded to residual docking error only."""
        result = self.policy.correct(Pose2D(1.0, 2.0, 0.0), BasketObservation(((0, 0), (2, 0), (2, 2), (0, 2)), translation_m=(0.01, 0.0), rotation_deg=6.0))
        self.assertFalse(result.approved)


if __name__ == '__main__':
    unittest.main()
