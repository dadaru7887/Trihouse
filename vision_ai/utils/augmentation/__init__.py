"""Augmentation split so training and scoring never share an implementation.

    rng.py         seeds the augmentation stream, leaves the training RNG alone
    primitives.py  single effects (low light, blur, condensation, glare, frost)
    scenarios.py   the recipe registry: TRAIN_RECIPES and the eval tiers
"""

from .rng import (  # noqa: F401
    DEFAULT_AUGMENTATION_SEED,
    augmentation_rng,
    configure_augmentation_seed,
    isolated_augmentation_random_state,
)
