"""Augmentation split so training and scoring never share an implementation.

    rng.py         seeds the augmentation stream, leaves the training RNG alone
    primitives.py  single effects (low light, blur, condensation, glare, frost)
    scenarios.py   the recipe registry: TRAIN_RECIPES and the eval tiers

Only the rng helpers are re-exported here; import the submodule for the rest,
as every consumer does:

    from vision_ai.utils.augmentation import scenarios
"""

from .rng import (  # noqa: F401
    DEFAULT_AUGMENTATION_SEED,
    augmentation_rng,
    configure_augmentation_seed,
    isolated_augmentation_random_state,
)
