import importlib.util
from pathlib import Path

import numpy as np
import torch


def load_training_module():
    from vision_ai.models.perception.trainer.yoloe_trainer import _load_augmentation_module

    return _load_augmentation_module(None)


def test_augmentation_rng_restarts_from_fixed_seed() -> None:
    from vision_ai.utils.augmentation.rng import augmentation_rng, configure_augmentation_seed

    configure_augmentation_seed(42)
    first = augmentation_rng(None).integers(0, 1_000_000, size=8).tolist()
    configure_augmentation_seed(42)
    second = augmentation_rng(None).integers(0, 1_000_000, size=8).tolist()

    assert first == second


def test_augmentation_rng_is_independent_of_training_global_seed() -> None:
    """학습 seed 를 바꿔도 증강 난수열은 그대로여야 한다."""
    import random

    from vision_ai.utils.augmentation.rng import augmentation_rng, configure_augmentation_seed

    configure_augmentation_seed(42)
    random.seed(17)
    np.random.seed(17)
    first = augmentation_rng(None).integers(0, 1_000_000, size=8).tolist()

    configure_augmentation_seed(42)
    random.seed(3407)
    np.random.seed(3407)
    second = augmentation_rng(None).integers(0, 1_000_000, size=8).tolist()

    assert first == second


def test_training_frost_augmentations_do_not_download_remote_textures() -> None:
    module = load_training_module()
    module._load_frost_texture = lambda url: (_ for _ in ()).throw(AssertionError("network access"))
    image = np.full((64, 64, 3), 128, dtype=np.uint8)
    module.configure_augmentation_seed(42)
    for augmentation in (
        module._s4_frost,
        module._s4_night_frost,
        module._s5_lowlight_frost,
        module._s5_frost_glare,
    ):
        result = augmentation(image.copy())
        assert result.shape == image.shape


def test_mixed_augmentation_does_not_consume_model_torch_rng(monkeypatch) -> None:
    module = load_training_module()
    # monkeypatch so the swapped pool is put back; the module is a singleton and
    # a leaked pool breaks every later test that reads it.
    monkeypatch.setattr(module, "MIXED_POOL",
                        [lambda image: np.full_like(image, int(torch.rand(1).item() * 255))])
    monkeypatch.setattr(module, "_active_pool", None)
    image = np.zeros((4, 4, 3), dtype=np.uint8)

    module.configure_augmentation_seed(42)
    torch.manual_seed(17)
    expected_next = torch.rand(1).item()
    torch.manual_seed(17)
    first = module.mixed_augmentation(image)
    actual_next = torch.rand(1).item()

    module.configure_augmentation_seed(42)
    torch.manual_seed(3407)
    second = module.mixed_augmentation(image)

    assert np.array_equal(first, second)
    assert actual_next == expected_next
