"""RNG for online augmentation, kept separate from the training RNG.

Called from the training path only:
    yoloe_trainer.train() -> configure_augmentation_seed(aug_seed)
    augmentation_recipes.mixed_augmentation() -> isolated_augmentation_random_state()

Flow: configure_augmentation_seed() fixes a parent stream; each augmentation
draws a child seed from it, runs, and restores the training RNG state.
"""

from contextlib import contextmanager
import random

import numpy as np
import torch

DEFAULT_AUGMENTATION_SEED = 42

# Parent stream; each augmentation call draws a child seed from it.
_augmentation_seed = DEFAULT_AUGMENTATION_SEED
_augmentation_seed_stream = np.random.default_rng(DEFAULT_AUGMENTATION_SEED)


def configure_augmentation_seed(seed):
    """Restart the augmentation stream at `seed`. Training RNGs untouched."""
    global _augmentation_seed, _augmentation_seed_stream
    _augmentation_seed = int(seed)
    _augmentation_seed_stream = np.random.default_rng(_augmentation_seed)


def augmentation_rng(seed=None):
    """Return an independent RNG for one augmentation call.

    Fixed to `seed` when given, otherwise drawn from the parent stream.
    """
    if seed is not None:
        return np.random.default_rng(int(seed))
    child_seed = int(_augmentation_seed_stream.integers(0, np.iinfo(np.uint32).max))
    return np.random.default_rng(child_seed)


@contextmanager
def isolated_augmentation_random_state():
    """Run one augmentation on an augmentation seed, then restore training RNGs.

    S1-S5 recipes use the global random/np.random/torch, so this saves those
    three states on entry and puts them back on exit.
    """
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
