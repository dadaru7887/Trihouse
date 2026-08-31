"""S1-S5 warehouse degradation scenarios, composed from primitives.

Training-time only. The robot never augments what the camera gives it.

Called from:
    yoloe_trainer._default_components() -> configure_augmentation_seed, A,
                                           mixed_augmentation

Flow: mixed_augmentation() draws one function from MIXED_POOL per image and
runs it under an isolated augmentation RNG.

    S1 driving      gamma / motion blur / colour jitter      3 functions
    S2 condensation                                          1 function
    S3 glare                                                 1 function
    S4 frost        frost / night frost                      2 functions
    S5 compound     two S1-S4 effects, motion blur last      5 functions
"""

import random

import albumentations as A
import numpy as np
from PIL import Image
from torchvision import transforms

from vision_ai.utils.augmentation.primitives import (
    add_condensation, add_glare, add_motion_blur, adjust_gamma,
    generate_frost_overlay_chunky, synthesize_night_frost_chunky,
)
from vision_ai.utils.augmentation.rng import (
    configure_augmentation_seed, isolated_augmentation_random_state,
)

# yoloe_trainer reaches into this module for these three names.
__all__ = ["A", "configure_augmentation_seed", "configure_pool", "mixed_augmentation",
           "MIXED_POOL", "SCENARIOS", "SCENARIO_OF", "apply_scenario", "pool_for"]

# Functions mixed_augmentation currently draws from; configure_pool() narrows it.
_active_pool = None

# 증강 전용 난수 스트림의 기본 seed.
#
# **여기서 전역 RNG(random / np.random / torch)를 건드리지 않는다.** 예전에는
# 이 자리에서 세 개를 전부 seed(42) 로 고정했는데, `yoloe_trainer.train()` 이
# `seed_everything(config.seed)` **직후에** 이 모듈을 import 하므로 사용자가 준
# --seed 가 그 자리에서 42 로 덮였다. 예외가 아니라 "재현이 안 된다" 로만
# 나타나서 원인에서 가장 먼 버그였다.
#
# 학습 seed 는 호출부(`utils/reproducibility.seed_everything`)가, 증강 seed 는

# ============================================================
# 3. S1~S5 다 섞기 (mixed_augmentation)
# ============================================================
# ── S1~S5 튜닝 결과를 하나의 풀(pool)로 섞기 ──
# 지금까지 candidate-group에서 눈으로 확정한 값들을 그대로 가져와서,
# 매 학습 스텝마다 이 풀에서 하나를 무작위로 뽑아 적용합니다.
# (전부 RGB 이미지 기준 -- 학습 파이프라인이 RGB라서 candidate-group 셀과 달리 BGR 변환 없음)

def _s1_gamma(image):
    """S1: darken with gamma in 0.55-0.65."""
    # gamma < 1 darkens. 0.65 is the mild end, 0.55 the strong end; drawn
    # continuously so the model sees the whole band, not two fixed levels.
    gamma = random.uniform(0.55, 0.65)
    return adjust_gamma(image, gamma)


def _s1_motion_blur(image):
    """S1: motion blur at 18 degrees, kernel 45 or 70."""
    # Kernel length in pixels: 45 = a short shake, 70 = a long one.
    ksize = random.choice([45, 70])
    # 18 degrees is the robot's usual travel direction, so the smear runs
    # along the way it moves.
    return add_motion_blur(image, ksize, 18)


def _s1_color_jitter(image):
    """S1: jitter brightness, contrast, saturation and hue."""
    pil_img = Image.fromarray(image)
    # Max relative shift per channel: brightness .5, contrast .4,
    # saturation .3, hue .05. Hue stays small so colours do not flip.
    jitter = transforms.ColorJitter(0.5, 0.4, 0.3, 0.05)
    return np.array(jitter(pil_img))


def _s2_condensation(image):
    """S2: condensation, one of five coverage/intensity/placement recipes."""
    h, w = image.shape[:2]
    # (coverage, intensity, centre). coverage = how much of the frame the
    # droplet field spans; intensity = how opaque the haze is;
    # centre = None means a random point in the middle 40% of the frame.
    recipe = random.choice([
        (0.35, 0.18, None),                              # light film over the middle
        (0.80, 0.34, None),                              # heavy film over most of the frame
        (0.55, 0.24, (int(w * 0.50), int(h * 0.12))),    # fog banked along the top edge
        (0.55, 0.24, (int(w * 0.50), int(h * 0.88))),    # fog banked along the bottom edge
        (0.42, 0.48, None),                              # small but very opaque patch
    ])
    coverage, intensity, center = recipe
    return add_condensation(image, coverage, intensity, center)


def _s3_glare(image):
    """S3: glare, one of five intensity/size/placement recipes."""
    h, w = image.shape[:2]
    # (intensity, size_ratio, centre). intensity = how white the core goes;
    # size_ratio = radius as a fraction of the shorter side;
    # centre = None means anywhere in the frame.
    recipe = random.choice([
        (0.65, 0.30, None),                             # bright spot, position unconstrained
        (0.45, 0.25, (int(w * 0.5), int(h * 0.30))),    # ceiling light, mild
        (0.70, 0.45, (int(w * 0.5), int(h * 0.30))),    # ceiling light, strong
        (0.40, 0.30, (int(w * 0.5), int(h * 0.85))),    # floor reflection, mild
        (0.65, 0.55, (int(w * 0.5), int(h * 0.85))),    # floor reflection, strong
    ])
    intensity, size_ratio, center = recipe
    return add_glare(image, intensity, size_ratio, center)


def _s4_frost(image):
    """S4: frost overlay, mild or strong coverage."""
    # (coverage, temperature_delta). coverage = how far the frost blobs
    # spread from the corners; temperature_delta = opacity of the frost.
    coverage, temperature = random.choice([
        (0.15, 0.30),   # thin rime at the corners
        (0.45, 0.55),   # thick frost over much of the lens
    ])
    # n_anchors=4 grows the frost inward from all four corners.
    return generate_frost_overlay_chunky(image, coverage, temperature, seed=None, n_anchors=4)


def _s4_night_frost(image):
    """S4: low exposure plus frost plus blur."""
    # (exposure_ratio, coverage, temperature_delta, blur_strength).
    # exposure_ratio < 1 darkens; the freezer aisle is dim as well as frosted.
    exposure, coverage, temperature, blur_strength = random.choice([
        (0.45, 0.35, 0.45, 1.0),   # dim aisle, moderate frost
        (0.60, 0.35, 0.45, 1.3),   # darker still, blurrier
    ])
    return synthesize_night_frost_chunky(
        image, exposure_ratio=exposure, coverage_ratio=coverage,
        temperature_delta=temperature, blur_strength=blur_strength,
    )


# S5 pairs two S1-S4 effects and always ends with motion blur, because a
# moving robot smears whatever the lens already has on it.
# Each function draws mild (first branch) or strong (second) with equal odds.
def _s5_lowlight_condensation(image):
    """S5: gamma -> condensation -> motion blur."""
    if random.random() < 0.5:
        # mild: gamma .65, light condensation, short 45px smear
        return add_motion_blur(add_condensation(adjust_gamma(image, 0.65), 0.35, 0.18), 45, 18)
    # strong: gamma .55, heavy condensation, long 70px smear
    return add_motion_blur(add_condensation(adjust_gamma(image, 0.55), 0.80, 0.34), 70, 18)


def _s5_lowlight_glare(image):
    """S5: gamma -> glare -> motion blur."""
    h, w = image.shape[:2]
    if random.random() < 0.5:
        # mild: gamma .65, ceiling glare, short smear
        return add_motion_blur(
            add_glare(adjust_gamma(image, 0.65), 0.45, 0.25, (int(w * 0.5), int(h * 0.30))), 45, 18)
    # strong: gamma .55, floor glare, long smear
    return add_motion_blur(
        add_glare(adjust_gamma(image, 0.55), 0.65, 0.55, (int(w * 0.5), int(h * 0.85))), 70, 18)


def _s5_condensation_glare(image):
    """S5: condensation -> glare -> motion blur."""
    h, w = image.shape[:2]
    if random.random() < 0.5:
        # mild: top-edge fog, then ceiling glare through it, short smear
        return add_motion_blur(
            add_glare(add_condensation(image, 0.55, 0.24, (int(w * 0.5), int(h * 0.12))),
                      0.45, 0.25, (int(w * 0.5), int(h * 0.30))), 45, 18)
    # strong: dense fog patch, then floor glare, long smear
    return add_motion_blur(
        add_glare(add_condensation(image, 0.42, 0.48),
                  0.65, 0.55, (int(w * 0.5), int(h * 0.85))), 70, 18)


def _s5_lowlight_frost(image):
    """S5: gamma -> frost -> motion blur."""
    if random.random() < 0.5:
        # mild: gamma .65, thin rime, short smear
        frosted = generate_frost_overlay_chunky(adjust_gamma(image, 0.65), 0.15, 0.30, seed=None, n_anchors=4)
        return add_motion_blur(frosted, 45, 18)
    # strong: gamma .55, thick frost, long smear
    frosted = generate_frost_overlay_chunky(adjust_gamma(image, 0.55), 0.45, 0.55, seed=None, n_anchors=4)
    return add_motion_blur(frosted, 70, 18)


def _s5_frost_glare(image):
    """S5: frost -> glare -> motion blur."""
    h, w = image.shape[:2]
    if random.random() < 0.5:
        # mild: thin rime, ceiling glare scattering off it, short smear
        frosted = generate_frost_overlay_chunky(image, 0.15, 0.30, seed=None, n_anchors=4)
        return add_motion_blur(add_glare(frosted, 0.45, 0.25, (int(w * 0.5), int(h * 0.30))), 45, 18)
    # strong: thick frost, floor glare, long smear
    frosted = generate_frost_overlay_chunky(image, 0.45, 0.55, seed=None, n_anchors=4)
    return add_motion_blur(add_glare(frosted, 0.65, 0.55, (int(w * 0.5), int(h * 0.85))), 70, 18)


# One entry per augmentation function; mixed_augmentation draws from this.
MIXED_POOL = [
    _s1_gamma, _s1_motion_blur, _s1_color_jitter,          # S1
    _s2_condensation,                                       # S2
    _s3_glare,                                               # S3
    _s4_frost, _s4_night_frost,                              # S4
    _s5_lowlight_condensation, _s5_lowlight_glare,           # S5
    _s5_condensation_glare, _s5_lowlight_frost, _s5_frost_glare,
]


# Which scenario each pool function belongs to. Leave-one-out experiments and
# per-scenario evaluation both key off this.
SCENARIO_OF = {
    "_s1_gamma": "S1", "_s1_motion_blur": "S1", "_s1_color_jitter": "S1",
    "_s2_condensation": "S2",
    "_s3_glare": "S3",
    "_s4_frost": "S4", "_s4_night_frost": "S4",
    "_s5_lowlight_condensation": "S5", "_s5_lowlight_glare": "S5",
    "_s5_condensation_glare": "S5", "_s5_lowlight_frost": "S5",
    "_s5_frost_glare": "S5",
}
SCENARIOS = ("S1", "S2", "S3", "S4", "S5")


def pool_for(exclude=frozenset()):
    """Return MIXED_POOL without the named scenarios' functions."""
    unknown = set(exclude) - set(SCENARIOS)
    if unknown:
        raise ValueError(f"unknown scenario(s): {sorted(unknown)}")
    # Untagged entries (a test double, a drop-in pool) cannot be excluded by
    # scenario, so they stay.
    pool = [fn for fn in MIXED_POOL if SCENARIO_OF.get(fn.__name__) not in exclude]
    if not pool:
        raise ValueError("holding out every scenario leaves an empty pool")
    return pool


def apply_scenario(image, scenario):
    """Apply one scenario to an image, for per-corruption evaluation."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
    choices = [fn for fn in MIXED_POOL if SCENARIO_OF.get(fn.__name__) == scenario]
    if not choices:
        raise ValueError(f"no functions tagged {scenario} in the pool")
    with isolated_augmentation_random_state():
        return random.choice(choices)(image)


def mixed_augmentation(image, **kwargs):
    """Pick one function from the active pool and apply it, on the augmentation RNG."""
    with isolated_augmentation_random_state():
        return random.choice(_active_pool or MIXED_POOL)(image)


def configure_pool(exclude=frozenset()):
    """Set which scenarios mixed_augmentation may draw from, for leave-one-out."""
    global _active_pool
    _active_pool = pool_for(exclude)
    return _active_pool


