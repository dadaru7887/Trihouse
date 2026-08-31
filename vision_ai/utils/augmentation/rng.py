"""증강 전용 난수 스트림.

학습 난수와 증강 난수를 갈라 두는 것이 이 모듈의 전부다. 증강이 학습 난수열을
소비하면 같은 seed 로도 학습이 재현되지 않는다.

**모듈 최상위에서 전역 RNG(random / np.random / torch)를 건드리지 않는다.**
예전에는 그렇게 했다가, `yoloe_trainer.train()` 이 `seed_everything(config.seed)`
직후에 증강 모듈을 import 하는 탓에 사용자가 준 --seed 가 그 자리에서 덮였다.
"""

from contextlib import contextmanager
import random

import numpy as np
import torch

# 아래 `configure_augmentation_seed()` 가 각자 책임진다.
DEFAULT_AUGMENTATION_SEED = 42

_augmentation_seed = DEFAULT_AUGMENTATION_SEED
_augmentation_seed_stream = np.random.default_rng(DEFAULT_AUGMENTATION_SEED)


def configure_augmentation_seed(seed):
    """Reset only the online-augmentation RNG stream."""
    global _augmentation_seed, _augmentation_seed_stream
    _augmentation_seed = int(seed)
    _augmentation_seed_stream = np.random.default_rng(_augmentation_seed)


def augmentation_rng(seed=None):
    if seed is not None:
        return np.random.default_rng(int(seed))
    child_seed = int(_augmentation_seed_stream.integers(0, np.iinfo(np.uint32).max))
    return np.random.default_rng(child_seed)


@contextmanager
def isolated_augmentation_random_state():
    """Run one augmentation without consuming the model-training RNG state."""
    python_state = random.getstate()
    numpy_state = np.random.get_state()
    torch_state = torch.random.get_rng_state()
    call_seed = int(_augmentation_seed_stream.integers(0, np.iinfo(np.uint32).max))
    random.seed(call_seed)
    np.random.seed(call_seed)
    torch.manual_seed(call_seed)
    try:
        yield
    finally:
        random.setstate(python_state)
        np.random.set_state(numpy_state)
        torch.random.set_rng_state(torch_state)
