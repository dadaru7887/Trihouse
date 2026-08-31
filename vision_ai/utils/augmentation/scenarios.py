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
        unseen          one effect whose implementation training never runs.
        unseen_compound those unseen implementations stacked -- nothing in the
                        image comes from code training executed. Closest to a
                        real freezer aisle and the strongest claim available.

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
    generate_frost_overlay_chunky, generate_frost_overlay_v3, poisson_gaussian_noise,
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

    `mechanism` is the physical phenomenon; holdout works on it. `group` is
    where the recipe may be used: a scenario name for training recipes,
    "compound" or "unseen" for evaluation-only ones.
    """

    id: str
    group: str
    mechanism: str
    apply: Callable

    def __call__(self, image):
        return self.apply(image)


# Which primitives realise each mechanism. The holdout test runs the pool and
# checks that no excluded mechanism's primitives are reached, so every
# implementation of a phenomenon has to be listed here -- including the ones
# reserved for evaluation.
ATOMS_OF_MECHANISM = {
    "gamma": ("adjust_gamma", "gamma_brightness", "synthesize_low_light"),
    "motion_blur": ("add_motion_blur", "motion_blur"),
    "color_jitter": ("color_jitter",),
    "condensation": ("add_condensation",),
    "glare": ("add_glare",),
    "frost": ("generate_frost_overlay_chunky", "generate_frost_overlay_v3",
              "generate_frost_overlay_textured", "synthesize_night_frost",
              "synthesize_night_frost_chunky", "synthesize_night_frost_textured"),
    "defocus_blur": ("disc_blur", "edge_blur", "gaussian_blur", "scaled_blur",
                     "random_blur"),
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

# Helpers with no mechanism of their own; calling one is not a leak.
UNTRACKED_ATOMS = frozenset({"remap_label_text"})


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
           # 45px smear at 18 degrees, the robot's usual travel direction.
           lambda image: add_motion_blur(image, 45, 18)),
    Recipe("S1_motion_blur_long", "S1", "motion_blur",
           lambda image: add_motion_blur(image, 70, 18)),
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
# Never drawn during training. Two tiers, each answering a different question.

def _compound(*steps):
    """Chain single effects left to right into one compound recipe body."""
    def run(image):
        for step in steps:
            image = step(image)
        return image
    return run


# Tier 1 -- seen_compound. Every effect here also appears in TRAIN_RECIPES;
# only the stacking is new. Motion blur goes last because a moving robot
# smears whatever the lens already has on it.
EVAL_SEEN_COMPOUND = (
    Recipe("C_lowlight_condensation_mild", "seen_compound", "gamma+condensation+motion_blur",
           _compound(lambda i: adjust_gamma(i, 0.65), _condensation(0.35, 0.18),
                     lambda i: add_motion_blur(i, 45, 18))),
    Recipe("C_lowlight_condensation_strong", "seen_compound", "gamma+condensation+motion_blur",
           _compound(lambda i: adjust_gamma(i, 0.55), _condensation(0.80, 0.34),
                     lambda i: add_motion_blur(i, 70, 18))),
    Recipe("C_lowlight_glare_mild", "seen_compound", "gamma+glare+motion_blur",
           _compound(lambda i: adjust_gamma(i, 0.65), _glare(0.45, 0.25, _at(0.5, 0.30)),
                     lambda i: add_motion_blur(i, 45, 18))),
    Recipe("C_lowlight_glare_strong", "seen_compound", "gamma+glare+motion_blur",
           _compound(lambda i: adjust_gamma(i, 0.55), _glare(0.65, 0.55, _at(0.5, 0.85)),
                     lambda i: add_motion_blur(i, 70, 18))),
    Recipe("C_condensation_glare_mild", "seen_compound", "condensation+glare+motion_blur",
           _compound(_condensation(0.55, 0.24, _at(0.5, 0.12)),
                     _glare(0.45, 0.25, _at(0.5, 0.30)),
                     lambda i: add_motion_blur(i, 45, 18))),
    Recipe("C_condensation_glare_strong", "seen_compound", "condensation+glare+motion_blur",
           _compound(_condensation(0.42, 0.48), _glare(0.65, 0.55, _at(0.5, 0.85)),
                     lambda i: add_motion_blur(i, 70, 18))),
    Recipe("C_lowlight_frost_mild", "seen_compound", "gamma+frost+motion_blur",
           _compound(lambda i: adjust_gamma(i, 0.65), _frost(0.15, 0.30),
                     lambda i: add_motion_blur(i, 45, 18))),
    Recipe("C_lowlight_frost_strong", "seen_compound", "gamma+frost+motion_blur",
           _compound(lambda i: adjust_gamma(i, 0.55), _frost(0.45, 0.55),
                     lambda i: add_motion_blur(i, 70, 18))),
    Recipe("C_frost_glare_mild", "seen_compound", "frost+glare+motion_blur",
           _compound(_frost(0.15, 0.30), _glare(0.45, 0.25, _at(0.5, 0.30)),
                     lambda i: add_motion_blur(i, 45, 18))),
    Recipe("C_frost_glare_strong", "seen_compound", "frost+glare+motion_blur",
           _compound(_frost(0.45, 0.55), _glare(0.65, 0.55, _at(0.5, 0.85)),
                     lambda i: add_motion_blur(i, 70, 18))),
)

# Tier 2 -- unseen: implementations training never runs. Frost is the sharpest
# of these: generate_frost_overlay_v3 builds the same phenomenon from upscaled
# octave noise instead of stacked blobs, so scoring on it asks whether the
# model learned frost or learned one blob generator.
EVAL_UNSEEN = (
    Recipe("U_frost_crystal_mild", "unseen", "frost",
           lambda image: generate_frost_overlay_v3(image, 0.15, 0.30, seed=None)),
    Recipe("U_frost_crystal_thick", "unseen", "frost",
           lambda image: generate_frost_overlay_v3(image, 0.45, 0.55, seed=None)),
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

# Tier 3 -- unseen_compound: the freezer condition (dim, frosted, out of
# focus, noisy) assembled entirely from implementations training never ran.
# gamma_brightness darkens by a linear factor on top of the tone curve, unlike
# the pure LUT of adjust_gamma used in training.
EVAL_UNSEEN_COMPOUND = (
    Recipe("X_freezer_mild", "unseen_compound", "gamma+frost+defocus_blur+sensor_noise",
           _compound(lambda i: gamma_brightness(i, factor=0.6, gamma=1.1),
                     lambda i: generate_frost_overlay_v3(i, 0.15, 0.30, seed=None),
                     lambda i: disc_blur(i, strength=1.0),
                     lambda i: poisson_gaussian_noise(i, a=0.02, b=0.01, seed=None))),
    Recipe("X_freezer_strong", "unseen_compound", "gamma+frost+defocus_blur+sensor_noise",
           _compound(lambda i: gamma_brightness(i, factor=0.4, gamma=1.3),
                     lambda i: generate_frost_overlay_v3(i, 0.45, 0.55, seed=None),
                     lambda i: edge_blur(i, strength=1.5),
                     lambda i: poisson_gaussian_noise(i, a=0.04, b=0.02, seed=None))),
    Recipe("X_dim_defocus_noise", "unseen_compound", "gamma+defocus_blur+sensor_noise",
           _compound(lambda i: gamma_brightness(i, factor=0.5, gamma=0.9),
                     lambda i: gaussian_blur(i, strength=1.4),
                     lambda i: add_gaussian_noise(i, 12.0))),
)

EVAL_RECIPES = EVAL_SEEN_COMPOUND + EVAL_UNSEEN + EVAL_UNSEEN_COMPOUND
RECIPES = TRAIN_RECIPES + EVAL_RECIPES

# Tiers whose recipes may only use implementations training never runs.
STRICTLY_UNSEEN_GROUPS = ("unseen", "unseen_compound")
GROUPS = SCENARIOS + ("seen_compound", *STRICTLY_UNSEEN_GROUPS)

_BY_ID = {recipe.id: recipe for recipe in RECIPES}

# yoloe_trainer asserts this name exists; it is the callables of TRAIN_RECIPES.
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
