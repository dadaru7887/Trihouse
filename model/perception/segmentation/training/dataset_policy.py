"""증강을 offline 학습에만 제한하고 실시간 영상 원본을 지키는 정책."""

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar


class DatasetSplit(StrEnum):
    TRAIN = 'TRAIN'
    ORIGINAL_VALIDATION = 'ORIGINAL_VALIDATION'
    LOW_LIGHT_VALIDATION = 'LOW_LIGHT_VALIDATION'


@dataclass(frozen=True)
class DatasetManifest:
    train_ids: tuple[str, ...]
    original_validation_ids: tuple[str, ...]
    low_light_validation_ids: tuple[str, ...]


Frame = TypeVar('Frame')


class DatasetPolicy:
    def augment(self, sample_id: str, split: DatasetSplit, recipe: str) -> str:
        if split != DatasetSplit.TRAIN:
            raise ValueError('augmentation is restricted to offline training data')
        if not sample_id or not recipe:
            raise ValueError('sample and recipe are required')
        return f'{sample_id}|aug:{recipe}'

    def build_manifest(
        self,
        *,
        train_ids: tuple[str, ...],
        original_validation_ids: tuple[str, ...],
        low_light_validation_ids: tuple[str, ...],
    ) -> DatasetManifest:
        if not train_ids or not original_validation_ids or not low_light_validation_ids:
            raise ValueError('all dataset splits require at least one sample')
        split_sets = (set(train_ids), set(original_validation_ids), set(low_light_validation_ids))
        if any(left & right for index, left in enumerate(split_sets) for right in split_sets[index + 1:]):
            raise ValueError('dataset splits must be disjoint')
        return DatasetManifest(train_ids, original_validation_ids, low_light_validation_ids)

    @staticmethod
    def inference_input(frame: Frame) -> Frame:
        """실시간 카메라 frame은 바꾸지 않고 반환한다. 전처리는 증강과 다르다."""
        return frame
