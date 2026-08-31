"""Warehouse degradation recipes, split so training and scoring never overlap.

A recipe is one effect at one fixed setting. Every recipe names the single
mechanism it uses, so holding out a mechanism provably removes every recipe
that can produce it.

Two disjoint sets:
    TRAIN_RECIPES   16 single-mechanism recipes, the only thing training draws
    EVAL_RECIPES    scoring only, in three tiers of increasing strictness

        seen_compound   effects training saw individually, now stacked.
                        Weakest tier: only the combination is new. Report it
                        as compositional generalisation, never as robustness
                        to unseen corruption.
        unseen          one effect training never runs: defocus blur, sensor
                        noise, and a second way of darkening.
        unseen_compound those stacked -- nothing in the image comes from code
                        training executed. Closest to a real freezer aisle and
                        the strongest claim available.

Frost is the one trained mechanism with no unseen counterpart; verify it with
--holdout frost and score group S4.

Called from:
    yoloe_trainer._default_components() -> configure_pool, mixed_augmentation
    corruption_eval                     -> apply_recipe, apply_group
    tooling/augmentation_preview        -> apply_recipe

Flow: configure_pool() fixes which mechanisms are trainable, then
mixed_augmentation() draws one recipe per image, uniformly, under the
augmentation RNG.
"""

import random
from dataclasses import dataclass
from typing import Callable

import albumentations as A

from vision_ai.utils.augmentation.primitives import (
    add_condensation, add_gaussian_noise, add_glare, add_motion_blur, adjust_gamma,
    color_jitter, disc_blur, edge_blur, gamma_brightness, gaussian_blur,
    generate_frost_overlay_chunky, poisson_gaussian_noise,
)
from vision_ai.utils.augmentation.rng import (
    configure_augmentation_seed, isolated_augmentation_random_state,
)

__all__ = ["A", "configure_augmentation_seed", "configure_pool", "mixed_augmentation",
           "MIXED_POOL", "Recipe", "TRAIN_RECIPES", "EVAL_RECIPES", "RECIPES",
           "MECHANISMS", "ATOMS_OF_MECHANISM", "TRAIN_ATOMS", "EVAL_ONLY_ATOMS",
           "UNTRACKED_ATOMS", "SCENARIOS", "GROUPS", "STRICTLY_UNSEEN_GROUPS",
           "apply_recipe", "apply_group", "recipes_in", "pool_for"]

# Importing this module must not seed any global RNG. The training seed is
# owned by utils/reproducibility.seed_everything, the augmentation seed by
# configure_augmentation_seed.


@dataclass(frozen=True)
class Recipe:
    """One effect at one fixed setting.

    `mechanism` is the physical phenomenon; holdout works on it. A compound
    joins several with '+'. `group` says where the recipe may be used: S1..S4
    for training, seen_compound/unseen/unseen_compound for scoring only.
    """

    id: str
    group: str
    mechanism: str
    apply: Callable

    def __call__(self, image):
        """Apply the recipe, so a Recipe can be used wherever a function is."""
        return self.apply(image)


# Which primitives realise each mechanism. The holdout test runs the pool and
# checks that no excluded mechanism's primitives are reached, so every
# implementation of a phenomenon has to be listed here -- including the ones
# reserved for evaluation.
ATOMS_OF_MECHANISM = {
    "gamma": ("adjust_gamma", "gamma_brightness"),
    "motion_blur": ("add_motion_blur",),
    "color_jitter": ("color_jitter",),
    "condensation": ("add_condensation",),
    "glare": ("add_glare",),
    "frost": ("generate_frost_overlay_chunky",),
    "defocus_blur": ("disc_blur", "edge_blur", "gaussian_blur"),
    "sensor_noise": ("poisson_gaussian_noise", "add_gaussian_noise"),
}

# Mechanisms training may use. defocus_blur and sensor_noise are absent on
# purpose: a model that has never seen them is what makes them a valid test.
MECHANISMS = ("gamma", "motion_blur", "color_jitter", "condensation", "glare", "frost")

# The exact implementations training is allowed to run. Anything else is
# eval-only, which the holdout test enforces.
TRAIN_ATOMS = frozenset({"adjust_gamma", "add_motion_blur", "color_jitter",
                         "add_condensation", "add_glare",
                         "generate_frost_overlay_chunky"})
EVAL_ONLY_ATOMS = frozenset(
    atom for atoms in ATOMS_OF_MECHANISM.values() for atom in atoms) - TRAIN_ATOMS

# Primitives with no mechanism of their own; calling one is not a leak.
# Empty today -- every primitive maps to a mechanism.
UNTRACKED_ATOMS = frozenset()


# ---------------------------------------------------------------- training --
# One recipe per setting. Values were fixed by visual review; nothing here
# draws which setting to use, so a recipe id always means the same effect.
# Centres are given as fractions of the frame and resolved per image.

def _at(fx, fy):
    """Return a centre-picker placing a point at (fx, fy) of the frame."""
    return lambda image: (int(image.shape[1] * fx), int(image.shape[0] * fy))


def _condensation(coverage, intensity, center=None):
    """Build a condensation recipe body with fixed coverage/intensity/placement."""
    return lambda image: add_condensation(image, coverage, intensity,
                                          center(image) if center else None)


def _glare(intensity, size_ratio, center=None):
    """Build a glare recipe body with fixed intensity/size/placement."""
    return lambda image: add_glare(image, intensity, size_ratio,
                                   center(image) if center else None)


def _frost(coverage, temperature):
    """Build a frost recipe body; n_anchors=4 grows frost from all four corners."""
    return lambda image: generate_frost_overlay_chunky(
        image, coverage, temperature, seed=None, n_anchors=4)


TRAIN_RECIPES = (
    # S1 driving: the robot is moving under warehouse lighting.
    Recipe("S1_gamma", "S1", "gamma",
           # gamma < 1 darkens; drawn in a band so the model sees the whole
           # range rather than two fixed levels.
           lambda image: adjust_gamma(image, random.uniform(0.55, 0.65))),
    Recipe("S1_motion_blur_short", "S1", "motion_blur",
           # 15px smear at 18 degrees, the robot's usual travel direction.
           # Kernel length is capped so a person stays labelable: past ~30px
           # on a 640px frame the figures smear into streaks, and a condition
           # nobody could annotate teaches and measures nothing.
           lambda image: add_motion_blur(image, 15, 18)),
    Recipe("S1_motion_blur_long", "S1", "motion_blur",
           lambda image: add_motion_blur(image, 25, 18)),
    Recipe("S1_color_jitter", "S1", "color_jitter",
           # Max relative shift: brightness .5, contrast .4, saturation .3,
           # hue .05. Hue stays small so colours do not flip.
           lambda image: color_jitter(image, 0.5, 0.4, 0.3, 0.05)),

    # S2 condensation: warm air on a cold lens. coverage = how wide the droplet
    # field spreads, intensity = how opaque the haze is.
    Recipe("S2_condensation_light_film", "S2", "condensation",
           _condensation(0.35, 0.18)),
    Recipe("S2_condensation_heavy_film", "S2", "condensation",
           _condensation(0.80, 0.34)),
    Recipe("S2_condensation_top_bank", "S2", "condensation",
           _condensation(0.55, 0.24, _at(0.50, 0.12))),
    Recipe("S2_condensation_bottom_bank", "S2", "condensation",
           _condensation(0.55, 0.24, _at(0.50, 0.88))),
    Recipe("S2_condensation_dense_patch", "S2", "condensation",
           _condensation(0.42, 0.48)),

    # S3 glare: ceiling fixtures and their reflection off the floor.
    # intensity = how white the core goes, size = radius / shorter side.
    Recipe("S3_glare_unplaced", "S3", "glare", _glare(0.65, 0.30)),
    Recipe("S3_glare_ceiling_mild", "S3", "glare",
           _glare(0.45, 0.25, _at(0.5, 0.30))),
    Recipe("S3_glare_ceiling_strong", "S3", "glare",
           _glare(0.70, 0.45, _at(0.5, 0.30))),
    Recipe("S3_glare_floor_mild", "S3", "glare",
           _glare(0.40, 0.30, _at(0.5, 0.85))),
    Recipe("S3_glare_floor_strong", "S3", "glare",
           _glare(0.65, 0.55, _at(0.5, 0.85))),

    # S4 frost: freezer aisle rime on the lens. coverage = spread from the
    # corners, temperature = opacity.
    Recipe("S4_frost_rime", "S4", "frost", _frost(0.15, 0.30)),
    Recipe("S4_frost_thick", "S4", "frost", _frost(0.45, 0.55)),
)

SCENARIOS = ("S1", "S2", "S3", "S4")


# ------------------------------------------------------------ evaluation --
# Never drawn during training. Three tiers, each answering a different question.

_TRAIN_BY_ID = {recipe.id: recipe for recipe in TRAIN_RECIPES}


def _chain(registry, *recipe_ids):
    """Apply the named recipes in order, so a compound is built from real recipes.

    Compounds hold no parameters of their own: change a recipe and every
    compound using it changes with it.
    """
    parts = [registry[rid] for rid in recipe_ids]

    def run(image):
        """Feed the image through each recipe in turn."""
        for part in parts:
            image = part(image)
        return image
    return run


def _mechanisms_of(registry, recipe_ids):
    """Join the mechanisms of the named recipes, for the compound's own label."""
    return "+".join(sorted({registry[rid].mechanism for rid in recipe_ids}))


def _compound(name, group, registry, *recipe_ids):
    """Build one compound recipe out of existing recipes from `registry`."""
    return Recipe(name, group, _mechanisms_of(registry, recipe_ids),
                  _chain(registry, *recipe_ids))


# Tier 1 -- seen_compound: training recipes stacked. Every effect here is one
# training already runs, so only the ordering is new; motion blur goes last
# because a moving robot smears whatever the lens already has on it.
# Read it as compositional generalisation, never as unseen-corruption robustness.
EVAL_SEEN_COMPOUND = (
    _compound("C_lowlight_condensation_mild", "seen_compound", _TRAIN_BY_ID,
              "S1_gamma", "S2_condensation_light_film", "S1_motion_blur_short"),
    _compound("C_lowlight_condensation_strong", "seen_compound", _TRAIN_BY_ID,
              "S1_gamma", "S2_condensation_heavy_film", "S1_motion_blur_long"),
    _compound("C_lowlight_glare_mild", "seen_compound", _TRAIN_BY_ID,
              "S1_gamma", "S3_glare_ceiling_mild", "S1_motion_blur_short"),
    _compound("C_lowlight_glare_strong", "seen_compound", _TRAIN_BY_ID,
              "S1_gamma", "S3_glare_floor_strong", "S1_motion_blur_long"),
    _compound("C_condensation_glare_mild", "seen_compound", _TRAIN_BY_ID,
              "S2_condensation_top_bank", "S3_glare_ceiling_mild", "S1_motion_blur_short"),
    _compound("C_condensation_glare_strong", "seen_compound", _TRAIN_BY_ID,
              "S2_condensation_dense_patch", "S3_glare_floor_strong", "S1_motion_blur_long"),
    _compound("C_lowlight_frost_mild", "seen_compound", _TRAIN_BY_ID,
              "S1_gamma", "S4_frost_rime", "S1_motion_blur_short"),
    _compound("C_lowlight_frost_strong", "seen_compound", _TRAIN_BY_ID,
              "S1_gamma", "S4_frost_thick", "S1_motion_blur_long"),
    _compound("C_frost_glare_mild", "seen_compound", _TRAIN_BY_ID,
              "S4_frost_rime", "S3_glare_ceiling_mild", "S1_motion_blur_short"),
    _compound("C_frost_glare_strong", "seen_compound", _TRAIN_BY_ID,
              "S4_frost_thick", "S3_glare_floor_strong", "S1_motion_blur_long"),
)

# Tier 2 -- unseen: one effect whose implementation training never runs.
# Every mechanism here is absent from training entirely, so a score is about
# generalising to a corruption type, not to a second implementation of a
# trained one. Frost has no second implementation, so frost is verified by
# holdout (--holdout frost, then score S4) rather than by this tier.
EVAL_UNSEEN = (
    Recipe("U_lowlight_linear_mild", "unseen", "gamma",
           # Darkens by a linear factor on top of the tone curve, unlike the
           # pure LUT of adjust_gamma used in training.
           lambda image: gamma_brightness(image, factor=0.6, gamma=1.1)),
    Recipe("U_lowlight_linear_strong", "unseen", "gamma",
           lambda image: gamma_brightness(image, factor=0.4, gamma=1.3)),
    Recipe("U_defocus_disc", "unseen", "defocus_blur",
           lambda image: disc_blur(image, strength=1.2)),
    Recipe("U_defocus_edge", "unseen", "defocus_blur",
           lambda image: edge_blur(image, strength=1.4)),
    Recipe("U_defocus_gaussian", "unseen", "defocus_blur",
           lambda image: gaussian_blur(image, strength=1.4)),
    Recipe("U_noise_read", "unseen", "sensor_noise",
           # Plain additive noise, sigma in 0-255 units.
           lambda image: add_gaussian_noise(image, 12.0)),
    Recipe("U_noise_shot", "unseen", "sensor_noise",
           # Signal-dependent shot noise (a) plus read noise (b).
           lambda image: poisson_gaussian_noise(image, a=0.02, b=0.01, seed=None)),
)

_UNSEEN_BY_ID = {recipe.id: recipe for recipe in EVAL_UNSEEN}

# Tier 3 -- unseen_compound: the freezer condition (dim, frosted, out of focus,
# noisy) built only from tier-2 recipes, so no code training ran touches the
# image. The strongest claim available without real degraded footage.
EVAL_UNSEEN_COMPOUND = (
    _compound("X_freezer_mild", "unseen_compound", _UNSEEN_BY_ID,
              "U_lowlight_linear_mild", "U_defocus_disc", "U_noise_read"),
    _compound("X_freezer_strong", "unseen_compound", _UNSEEN_BY_ID,
              "U_lowlight_linear_strong", "U_defocus_edge", "U_noise_shot"),
    _compound("X_dim_defocus_noise", "unseen_compound", _UNSEEN_BY_ID,
              "U_lowlight_linear_mild", "U_defocus_gaussian", "U_noise_shot"),
)

EVAL_RECIPES = EVAL_SEEN_COMPOUND + EVAL_UNSEEN + EVAL_UNSEEN_COMPOUND
RECIPES = TRAIN_RECIPES + EVAL_RECIPES

# Tiers whose recipes may only use implementations training never runs.
STRICTLY_UNSEEN_GROUPS = ("unseen", "unseen_compound")
GROUPS = SCENARIOS + ("seen_compound", *STRICTLY_UNSEEN_GROUPS)

_BY_ID = {recipe.id: recipe for recipe in RECIPES}

# Back-compat alias: the callables of TRAIN_RECIPES. Read by
# tests/worker/test_yoloe_backend.py and test_augmentation_behaviour_lock.py.
MIXED_POOL = [recipe.apply for recipe in TRAIN_RECIPES]

# Which recipes mixed_augmentation currently draws from; configure_pool narrows it.
_active_pool = None


def recipes_in(group):
    """Return the recipes belonging to one scenario or evaluation tier."""
    if group not in GROUPS:
        raise ValueError(f"unknown group: {group}")
    return [recipe for recipe in RECIPES if recipe.group == group]


def pool_for(exclude=frozenset()):
    """Return the training recipes left after holding out the named mechanisms.

    A recipe is dropped when its mechanism is excluded, so no held-out effect
    can reach training through any recipe.
    """
    unknown = set(exclude) - set(MECHANISMS)
    if unknown:
        raise ValueError(f"unknown mechanism(s): {sorted(unknown)}")
    pool = [recipe for recipe in TRAIN_RECIPES if recipe.mechanism not in exclude]
    if not pool:
        raise ValueError("holding out every mechanism leaves an empty pool")
    return pool


def configure_pool(exclude=frozenset()):
    """Set which mechanisms mixed_augmentation may draw, for leave-one-out."""
    global _active_pool
    _active_pool = pool_for(exclude)
    return _active_pool


def mixed_augmentation(image, **kwargs):
    """Draw one training recipe uniformly and apply it, on the augmentation RNG.

    Uniform over recipes, not over scenarios, so every recipe gets the same
    exposure and no effect is under-sampled by how the scenarios are grouped.
    """
    with isolated_augmentation_random_state():
        return random.choice(_active_pool or list(TRAIN_RECIPES))(image)


def apply_recipe(image, recipe_id):
    """Apply one named recipe, for per-recipe evaluation and previews."""
    if recipe_id not in _BY_ID:
        raise ValueError(f"unknown recipe: {recipe_id}")
    with isolated_augmentation_random_state():
        return _BY_ID[recipe_id](image)


def apply_group(image, group):
    """Apply one recipe drawn from a scenario or evaluation tier."""
    with isolated_augmentation_random_state():
        return random.choice(recipes_in(group))(image)
