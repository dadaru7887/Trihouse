"""증강 동작을 해시로 고정한다 — 리팩터링이 그림을 바꾸지 않았음을 보이는 용도.

albumentations/cv2 가 없는 환경에서는 건너뛴다.
"""

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("albumentations")
pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

RECIPES = Path("vision_ai/utils/augmentation/scenarios.py")


def _load():
    spec = importlib.util.spec_from_file_location("aug_lock", RECIPES)
    module = importlib.util.module_from_spec(spec)
    sys.modules["aug_lock"] = module
    spec.loader.exec_module(module)
    return module


def _image():
    rng = np.random.default_rng(0)
    return rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)


def test_the_pool_holds_every_scenario() -> None:
    module = _load()
    names = [fn.__name__ for fn in module.MIXED_POOL]

    assert len(names) == 12, names
    for prefix, count in (("_s1_", 3), ("_s2_", 1), ("_s3_", 1), ("_s4_", 2), ("_s5_", 5)):
        assert sum(n.startswith(prefix) for n in names) == count, (prefix, names)


@pytest.mark.parametrize("seed", [42, 7])
def test_the_same_seed_reproduces_the_same_image(seed: int) -> None:
    """분할 전후로 이 해시가 같아야 그림이 안 바뀐 것이다."""
    digests = []
    for _ in range(2):
        module = _load()
        module.configure_augmentation_seed(seed)
        out = module.mixed_augmentation(_image())
        digests.append(hashlib.sha256(np.ascontiguousarray(out)).hexdigest())

    assert digests[0] == digests[1], "같은 seed 인데 결과가 다릅니다"


def test_augmentation_does_not_disturb_the_training_rng() -> None:
    """증강이 학습 난수열을 소비하면 학습 재현성이 깨진다."""
    import random

    module = _load()
    module.configure_augmentation_seed(42)

    random.seed(999)
    before = [random.random() for _ in range(3)]
    random.seed(999)
    module.mixed_augmentation(_image())
    after = [random.random() for _ in range(3)]

    assert before == after
