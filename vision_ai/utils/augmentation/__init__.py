"""Augmentation for training: RNG isolation, single effects, S1-S5 scenarios.

    rng.py         seeds the augmentation stream, leaves the training RNG alone
    primitives.py  single effects (low light, blur, condensation, glare, frost)
    scenarios.py   S1-S5 compositions and MIXED_POOL
"""

from .rng import (  # noqa: F401
    DEFAULT_AUGMENTATION_SEED,
    augmentation_rng,
    configure_augmentation_seed,
    isolated_augmentation_random_state,
)
