"""Augmented training inputs are kept on disk, without changing what training sees.

    pytest vision_ai/tests/worker/test_augmentation_samples.py
"""

import numpy as np
import pytest

pytest.importorskip("albumentations")
cv2 = pytest.importorskip("cv2")

from vision_ai.models.perception.trainer.yoloe_trainer import AugmentationSampler
from vision_ai.utils.augmentation import scenarios


def _image() -> np.ndarray:
    return np.random.default_rng(0).integers(0, 255, (64, 80, 3), dtype=np.uint8)


def test_sampling_returns_exactly_what_training_would_get(tmp_path) -> None:
    scenarios.configure_pool()
    scenarios.configure_augmentation_seed(7)
    expected = [scenarios.mixed_augmentation(_image()) for _ in range(5)]
    scenarios.configure_augmentation_seed(7)
    sampler = AugmentationSampler(scenarios.draw_and_apply, tmp_path / "samples")

    for want in expected:
        assert np.array_equal(sampler(_image()), want)


def test_each_recipe_keeps_at_most_its_quota_side_by_side(tmp_path) -> None:
    scenarios.configure_pool()
    scenarios.configure_augmentation_seed(3)
    sampler = AugmentationSampler(scenarios.draw_and_apply, tmp_path / "samples", per_recipe=2)

    for _ in range(80):
        sampler(_image())

    files = sorted((tmp_path / "samples").iterdir())
    per_recipe = {}
    for path in files:
        recipe = next(r.id for r in scenarios.TRAIN_RECIPES if path.name.startswith(r.id + "_"))
        per_recipe[recipe] = per_recipe.get(recipe, 0) + 1
    assert per_recipe and max(per_recipe.values()) <= 2
    saved = cv2.imread(str(files[0]))
    assert saved.shape == (64, 160, 3)          # original | augmented


def test_an_unwritable_directory_never_stops_training(tmp_path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    scenarios.configure_pool()
    sampler = AugmentationSampler(scenarios.draw_and_apply, blocker / "samples")

    assert sampler(_image()).shape == (64, 80, 3)
