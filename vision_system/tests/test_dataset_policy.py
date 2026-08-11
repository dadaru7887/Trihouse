"""저조도 학습 증강과 dataset split 분리의 인수 테스트."""

import unittest

from vision_system.training.dataset_policy import DatasetPolicy, DatasetSplit


class DatasetPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = DatasetPolicy()

    def test_augmentation_is_allowed_only_for_training_samples(self) -> None:
        """Live or validation frames must not receive brightness/contrast correction."""
        self.assertEqual('train-1|aug:low-light', self.policy.augment('train-1', DatasetSplit.TRAIN, 'low-light'))
        with self.assertRaises(ValueError):
            self.policy.augment('val-original-1', DatasetSplit.ORIGINAL_VALIDATION, 'brightness')

    def test_original_and_low_light_validation_sets_are_disjoint(self) -> None:
        """Reported robust performance needs two independently named validation sets."""
        manifest = self.policy.build_manifest(
            train_ids=('train-1',), original_validation_ids=('val-1',), low_light_validation_ids=('low-1',),
        )
        self.assertEqual(('val-1',), manifest.original_validation_ids)
        self.assertEqual(('low-1',), manifest.low_light_validation_ids)
        with self.assertRaises(ValueError):
            self.policy.build_manifest(train_ids=('same',), original_validation_ids=('same',), low_light_validation_ids=('low-1',))

    def test_inference_frame_is_forwarded_without_augmentation(self) -> None:
        """YOLO gets camera pixels as received; image enhancement belongs to dataset creation only."""
        frame = object()
        self.assertIs(frame, self.policy.inference_input(frame))


if __name__ == '__main__':
    unittest.main()
