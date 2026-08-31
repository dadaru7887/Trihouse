"""Single optical-degradation effects: low light, blur, noise, condensation, glare, frost.

Every function takes an RGB uint8 image and returns one of the same shape.
Photometric only -- pixels change, masks and labels do not.

Called from `scenarios.py`, which composes these into the S1-S5 recipes;
nothing here knows about S1-S5. Randomness comes from `rng.augmentation_rng()`,
which keeps the training RNG untouched.

Effects that stack (`synthesize_*`) apply their parts in this order:
blur -> darken -> frost -> sensor noise.
"""

import io
import random

import cv2
import numpy as np
import requests
import torch
from PIL import Image, ImageFilter, ImageOps
from torchvision import transforms

from .rng import augmentation_rng as _augmentation_rng


def gamma_brightness(image, factor=None, gamma=None):
    """Darken by gamma curve and brightness factor (factor: random 0.1-0.5 if None)."""
    img = image.astype(np.float32) / 255.0
    if gamma is not None:
        img = np.power(img, gamma)
    if factor is None:
        factor = np.random.uniform(0.1, 0.5)
    img = img * factor
    return np.clip(img * 255.0, 0, 255).astype(np.uint8)


def poisson_gaussian_noise(image, a=0.02, b=0.01, seed=None):
    """Sensor-like noise: Poisson shot (scale `a`) plus Gaussian read (sigma `b`)."""
    rng = _augmentation_rng(seed)
    x = image.astype(np.float32) / 255.0
    lam = np.clip(x / a, 0, None)
    shot = rng.poisson(lam).astype(np.float32) * a
    read_noise = rng.normal(0, b, size=x.shape).astype(np.float32)
    noisy = shot + read_noise
    return np.clip(noisy * 255.0, 0, 255).astype(np.uint8)


def synthesize_low_light(image, exposure_ratio=None, gamma=None, a=0.02, b=0.01, seed=None):
    """Low light on its own: darken, then sensor noise.

    `exposure_ratio` scales brightness (random 0.15-0.55 if None); `gamma`
    bends the tone curve (random 0.8-1.3 if None). To combine with frost use
    `synthesize_night_frost`, which noises after the frost instead.
    """
    if exposure_ratio is None:
        exposure_ratio = np.random.uniform(0.15, 0.55)
    if gamma is None:
        gamma = np.random.uniform(0.8, 1.3)
    dark = gamma_brightness(image, factor=exposure_ratio, gamma=gamma)
    return poisson_gaussian_noise(dark, a=a, b=b, seed=seed)


# Four blurs. Every radius scales with the shorter side, so the effect is
# the same fraction of the frame at any resolution.

def gaussian_blur(image, strength=1.0):
    """Uniform blur, like haze in the air. Radius = 0.6% of the shorter side."""
    h, w = image.shape[:2]
    radius = max(1.0, min(h, w) * 0.006 * strength)
    return np.asarray(Image.fromarray(image).filter(ImageFilter.GaussianBlur(radius)))


def disc_blur(image, strength=1.0):
    """Disc-kernel blur: out-of-focus bokeh. Radius = 0.8% of the shorter side."""
    h, w = image.shape[:2]
    radius = max(2, int(min(h, w) * 0.008 * strength))
    yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    mask = (xx ** 2 + yy ** 2) <= radius ** 2
    kernel = mask.astype(np.float32)
    kernel /= kernel.sum()
    return cv2.filter2D(image, -1, kernel)


def motion_blur(image, strength=1.0, angle=None):
    """Smear along one direction. Length = 1.2% of the shorter side; random angle if None."""
    h, w = image.shape[:2]
    length = max(3, int(min(h, w) * 0.012 * strength))
    if length % 2 == 0:
        length += 1
    if angle is None:
        angle = np.random.uniform(0, 180)
    kernel = np.zeros((length, length), dtype=np.float32)
    kernel[length // 2, :] = 1.0
    M = cv2.getRotationMatrix2D((length / 2, length / 2), angle, 1)
    kernel = cv2.warpAffine(kernel, M, (length, length))
    kernel_sum = kernel.sum()
    if kernel_sum > 0:
        kernel /= kernel_sum
    return cv2.filter2D(image, -1, kernel)


def edge_blur(image, strength=1.0, edge_bias=1.8):
    """Sharp centre fading to blurred edges. `edge_bias` > 1 keeps the centre wider."""
    h, w = image.shape[:2]
    radius = max(1.0, min(h, w) * 0.012 * strength)
    blurred = np.asarray(
        Image.fromarray(image).filter(ImageFilter.GaussianBlur(radius))
    ).astype(np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cy, cx = h / 2, w / 2
    dist = np.sqrt(((yy - cy) / (h / 2)) ** 2 + ((xx - cx) / (w / 2)) ** 2)
    mask = np.clip(dist ** edge_bias, 0, 1)[..., None]
    out = image.astype(np.float32) * (1 - mask) + blurred * mask
    return np.clip(out, 0, 255).astype(np.uint8)


BLUR_FUNCS = {
    "gaussian": gaussian_blur,
    "disc": disc_blur,
    "motion": motion_blur,
    "edge": edge_blur,
}


def random_blur(image, strength_range=(0.8, 1.6), types=None):
    """Draw one blur type and one strength, then apply it.

    `types` defaults to disc and motion; pass a list to widen it to any key
    in BLUR_FUNCS.
    """
    types = types or ["disc", "motion"]
    choice = np.random.choice(types)
    strength = np.random.uniform(*strength_range)
    return BLUR_FUNCS[choice](image, strength=strength)


def scaled_blur(image, strength=1.0):
    """Alias for `gaussian_blur`, kept for a uniform strength argument."""
    return gaussian_blur(image, strength=strength)


def generate_frost_overlay_v3(image, coverage_ratio, temperature_delta, seed=None,
                               n_octaves=4, edge_bias=1.8, ambient_brightness=None,
                               n_anchors=None):
    """Fine window frost: fern-like crystals, built from upscaled noise.

    `coverage_ratio` 0-1 sets how much of the frame frosts over,
    `temperature_delta` 0-1 how opaque it gets. Frost grows inward from
    `n_anchors` random corners rather than from the centre.

    Steps: octave noise -> vein texture -> corner bias -> threshold by
    coverage -> sparkles -> tint and blend.
    """
    rng = _augmentation_rng(seed)
    h, w = image.shape[:2]

    combined = np.zeros((h, w), dtype=np.float32)
    for octave in range(n_octaves):
        res = 6 * (2 ** octave)
        low_res = rng.random((res, res)).astype(np.float32)
        upsampled = np.asarray(
            Image.fromarray((low_res * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
        ).astype(np.float32) / 255.0
        weight = 1.0 / (2 ** octave)
        combined += upsampled * weight
    combined /= combined.max()

    # Vein texture: ridge noise (1 - |2x-1|) cubed into sharp filaments,
    # then multiplied in so the field reads as crystals, not clouds.
    veins = np.zeros((h, w), dtype=np.float32)
    for octave in range(2):
        res = 10 * (3 ** octave)
        low_res = rng.random((res, res)).astype(np.float32)
        upsampled = np.asarray(
            Image.fromarray((low_res * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
        ).astype(np.float32) / 255.0
        ridge = 1.0 - np.abs(upsampled * 2 - 1)
        veins += (ridge ** 3) * (1.0 / (octave + 1))
    veins /= veins.max()
    combined = np.clip(combined * (0.7 + 0.55 * veins), 0, 1)
    combined /= combined.max()

    # Pick 1-2 corners; density falls off with distance from them.
    if n_anchors is None:
        n_anchors = int(rng.integers(1, 3))
    corners = np.array([[0, 0], [0, w], [h, 0], [h, w]], dtype=np.float32)
    anchor_idx = rng.choice(4, size=n_anchors, replace=False)
    anchors = corners[anchor_idx]

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    diag = float(np.sqrt(h ** 2 + w ** 2))
    anchor_bias = np.ones((h, w), dtype=np.float32)
    denom = 0.55 * diag  # distance at which density saturates; smaller = tighter to the corner
    for ay, ax in anchors:
        dist = np.sqrt((yy - ay) ** 2 + (xx - ax) ** 2) / denom
        anchor_bias = np.minimum(anchor_bias, dist)
    anchor_bias = np.clip(anchor_bias ** (edge_bias * 0.55), 0, 1)
    combined = combined * (0.35 + 0.65 * anchor_bias)

    threshold = 1.0 - coverage_ratio
    frost = np.clip((combined - threshold) / (1 - threshold + 1e-6), 0, 1)
    # Re-apply veins so saturated areas keep texture instead of going flat white.
    frost = frost * (0.72 + 0.28 * veins)

    n_sparkles = int(coverage_ratio * 300)
    sparkle_mask = np.zeros((h, w), dtype=np.float32)
    ys = rng.integers(0, h, n_sparkles)
    xs = rng.integers(0, w, n_sparkles)
    sparkle_mask[ys, xs] = 1.0
    sparkle_mask = np.asarray(
        Image.fromarray((sparkle_mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1))
    ).astype(np.float32) / 255.0
    frost = np.clip(frost + sparkle_mask * frost * 0.5, 0, 1)

    frost_img = Image.fromarray((frost * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
    frost = np.asarray(frost_img).astype(np.float32) / 255.0

    if ambient_brightness is None:
        ambient_brightness = float(image.mean())
    frost_tone = float(np.clip(ambient_brightness + 35, 40, 235))
    tone_rgb = np.array(
        [frost_tone - 6, frost_tone - 2, min(frost_tone + 8, 255)], dtype=np.float32
    )

    opacity = float(np.clip(temperature_delta, 0, 1) * 0.85)
    alpha = (frost * opacity)[..., None]
    frost_color = np.broadcast_to(tone_rgb, image.shape).astype(np.float32)
    out = image.astype(np.float32) * (1 - alpha) + frost_color * alpha
    return np.clip(out, 0, 255).astype(np.uint8)


def synthesize_night_frost(image, exposure_ratio, coverage_ratio, temperature_delta,
                            gamma=None, blur_strength=0.0, blur_fn=None, a=0.02, b=0.01, seed=None):
    """Low light plus fine window frost: blur -> darken -> frost -> noise.

    `blur_fn` defaults to `random_blur`, so the blur shape varies per call.
    """
    blur_fn = blur_fn or random_blur
    if gamma is None:
        gamma = np.random.uniform(0.8, 1.3)
    out = image
    if blur_strength > 0:
        out = blur_fn(out, strength_range=(blur_strength, blur_strength)) if blur_fn is random_blur else blur_fn(out, strength=blur_strength)
    dark = gamma_brightness(out, factor=exposure_ratio, gamma=gamma)
    frosted = generate_frost_overlay_v3(
        dark, coverage_ratio, temperature_delta,
        seed=seed, ambient_brightness=float(dark.mean())
    )
    noisy = poisson_gaussian_noise(frosted, a=a, b=b, seed=seed)
    return noisy


def generate_frost_overlay_chunky(image, coverage_ratio, temperature_delta, seed=None,
                                   ambient_brightness=None, n_blobs=None,
                                   blob_size_range=(0.03, 0.12), roughness=0.35,
                                   n_anchors=None, work_size=900):
    """Thick lumpy frost, the kind that cakes a lens in a freezer aisle.

    Stacks many wobbly-edged blobs, unlike the fine crystals of
    `generate_frost_overlay_v3`. `coverage_ratio` and `temperature_delta`
    mean the same here: spread and opacity, both 0-1.

    `work_size`: the mask is built on a canvas this many pixels on its long
    side and upsampled to the original, since blob count scales with area.
    """
    rng = _augmentation_rng(seed)
    h, w = image.shape[:2]

    scale = min(1.0, work_size / max(h, w))
    wh, ww = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
    diag = float(np.sqrt(wh ** 2 + ww ** 2))

    if n_anchors is None:
        n_anchors = int(rng.integers(1, 3))
    corners = np.array([[0, 0], [0, ww], [wh, 0], [wh, ww]], dtype=np.float32)
    anchor_idx = rng.choice(4, size=n_anchors, replace=False)
    anchors = corners[anchor_idx]

    if n_blobs is None:
        n_blobs = int(70 + coverage_ratio * 450)   # 70 blobs at coverage 0, 520 at coverage 1

    mask = np.zeros((wh, ww), dtype=np.float32)
    h, w = wh, ww          # the blob loop below works on the reduced canvas

    for _ in range(n_blobs):
        anchor = anchors[rng.integers(0, len(anchors))]
        spread = diag * (0.15 + 0.55 * coverage_ratio)
        cy = float(np.clip(anchor[0] + rng.normal(0, spread), 0, h - 1))
        cx = float(np.clip(anchor[1] + rng.normal(0, spread), 0, w - 1))
        radius = diag * rng.uniform(*blob_size_range)
        max_r = radius * (1.0 + roughness)   # largest radius the wobble can reach

        # Compute this blob only inside its bounding box, not the whole canvas.
        y0 = max(0, int(cy - max_r - 2))
        y1 = min(h, int(cy + max_r + 2))
        x0 = max(0, int(cx - max_r - 2))
        x1 = min(w, int(cx + max_r + 2))
        if y1 <= y0 or x1 <= x0:
            continue

        yy_local, xx_local = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        dy = yy_local - cy
        dx = xx_local - cx
        dist = np.sqrt(dy ** 2 + dx ** 2)
        theta = np.arctan2(dy, dx)
        # Three sine harmonics vary the radius by angle, giving a lumpy edge
        # instead of a circle. Random phase per blob so no two match.
        wobble = 1.0 + roughness * (
            0.5 * np.sin(theta * 3 + rng.uniform(0, 6.28))
            + 0.3 * np.sin(theta * 7 + rng.uniform(0, 6.28))
            + 0.2 * np.sin(theta * 11 + rng.uniform(0, 6.28))
        )
        local_radius = radius * wobble
        blob = np.clip(1.0 - dist / (local_radius + 1e-6), 0, 1)
        blob = blob ** 1.1     # falloff exponent; higher = sharper edge
        mask[y0:y1, x0:x1] = np.maximum(mask[y0:y1, x0:x1], blob)

    mask_img = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.0))
    # Upsample the reduced-canvas mask back to the source resolution.
    orig_h, orig_w = image.shape[:2]
    mask_img = mask_img.resize((orig_w, orig_h), Image.BICUBIC)
    mask = np.asarray(mask_img).astype(np.float32) / 255.0

    if ambient_brightness is None:
        ambient_brightness = float(image.mean())
    # Frost stays brighter than the scene by 2.3x or +90, whichever is larger,
    # so it remains visible on a dark frame.
    frost_tone = float(np.clip(max(ambient_brightness * 2.3, ambient_brightness + 90), 80, 250))
    tone_rgb = np.array(
        [frost_tone - 4, frost_tone - 1, min(frost_tone + 10, 255)], dtype=np.float32
    )

    opacity = float(np.clip(temperature_delta, 0, 1) * 0.95)
    alpha = (mask * opacity)[..., None]
    frost_color = np.broadcast_to(tone_rgb, image.shape).astype(np.float32)
    # Shade thicker parts of a blob brighter, for a sense of depth.
    shade = 0.85 + 0.15 * mask
    frost_color = frost_color * shade[..., None]

    out = image.astype(np.float32) * (1 - alpha) + frost_color * alpha
    return np.clip(out, 0, 255).astype(np.uint8)


def synthesize_night_frost_chunky(image, exposure_ratio, coverage_ratio, temperature_delta,
                                   gamma=None, blur_strength=0.0, blur_fn=None,
                                   n_blobs=None, blob_size_range=(0.03, 0.12), roughness=0.35,
                                   a=0.02, b=0.01, seed=None):
    """Low light plus chunky frost: blur -> darken -> frost -> noise.

    `n_blobs` overrides the count derived from `coverage_ratio`.
    """
    blur_fn = blur_fn or random_blur
    if gamma is None:
        gamma = np.random.uniform(0.8, 1.3)
    out = image
    if blur_strength > 0:
        out = blur_fn(out, strength_range=(blur_strength, blur_strength)) if blur_fn is random_blur else blur_fn(out, strength=blur_strength)
    dark = gamma_brightness(out, factor=exposure_ratio, gamma=gamma)
    frosted = generate_frost_overlay_chunky(
        dark, coverage_ratio, temperature_delta,
        seed=seed, ambient_brightness=float(dark.mean()),
        n_blobs=n_blobs, blob_size_range=blob_size_range, roughness=roughness,
    )
    noisy = poisson_gaussian_noise(frosted, a=a, b=b, seed=seed)
    return noisy


# Frost built from photographic texture. The procedural mask still controls
# shape and coverage; the photo supplies only the crystal detail inside it.
# Both are Unsplash-licensed macro shots and need no attribution.
FROST_TEXTURE_URLS = [
    "https://images.unsplash.com/photo-1762172189607-91ee2d5f1e34?fm=jpg&q=80&w=2000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1679287300349-e3ac52f291f1?fm=jpg&q=80&w=2000&auto=format&fit=crop",
]

_frost_texture_cache = {}


def _load_frost_texture(url):
    """Fetch and cache a frost texture as greyscale. The only network call here."""
    if url not in _frost_texture_cache:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        tex = Image.open(io.BytesIO(resp.content)).convert("L")
        _frost_texture_cache[url] = tex
    return _frost_texture_cache[url]


def _sample_texture_patch(h, w, seed=None):
    """Return an (h, w) detail patch from a frost photo, normalised to 0-1.

    Mirror-tiled 2x2 to hide seams, then randomly cropped and scaled so
    repeated calls do not show the same patch.
    """
    rng = _augmentation_rng(seed)
    url = FROST_TEXTURE_URLS[rng.integers(0, len(FROST_TEXTURE_URLS))]
    tex = _load_frost_texture(url)
    tw, th = tex.size

    tile = Image.new("L", (tw * 2, th * 2))
    tile.paste(tex, (0, 0))
    tile.paste(ImageOps.mirror(tex), (tw, 0))
    tile.paste(ImageOps.flip(tex), (0, th))
    tile.paste(ImageOps.mirror(ImageOps.flip(tex)), (tw, th))

    scale = rng.uniform(0.6, 1.4)
    need_w, need_h = int(w / scale) + 1, int(h / scale) + 1
    max_x = max(1, tile.width - need_w)
    max_y = max(1, tile.height - need_h)
    x0 = int(rng.integers(0, max_x)) if max_x > 1 else 0
    y0 = int(rng.integers(0, max_y)) if max_y > 1 else 0
    crop = tile.crop((x0, y0, x0 + need_w, y0 + need_h)).resize((w, h), Image.BICUBIC)

    arr = np.asarray(crop).astype(np.float32) / 255.0
    lo, hi = np.percentile(arr, 2), np.percentile(arr, 98)
    arr = np.clip((arr - lo) / max(hi - lo, 1e-6), 0, 1)
    return arr


def generate_frost_overlay_textured(image, coverage_ratio, temperature_delta, seed=None,
                                     ambient_brightness=None, n_blobs=None,
                                     blob_size_range=(0.03, 0.12), roughness=0.35,
                                     n_anchors=None, work_size=900, texture_strength=0.7):
    """Chunky blob mask for shape, photographic texture for crystal detail.

    `texture_strength` 0-1 mixes the two: 0 is the plain chunky mask,
    1 lets the photo fully modulate the alpha. Needs network access on first
    call to fetch the texture.
    """
    rng = _augmentation_rng(seed)
    h, w = image.shape[:2]

    scale = min(1.0, work_size / max(h, w))
    wh, ww = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
    diag = float(np.sqrt(wh ** 2 + ww ** 2))

    if n_anchors is None:
        n_anchors = int(rng.integers(1, 3))
    corners = np.array([[0, 0], [0, ww], [wh, 0], [wh, ww]], dtype=np.float32)
    anchor_idx = rng.choice(4, size=n_anchors, replace=False)
    anchors = corners[anchor_idx]

    if n_blobs is None:
        n_blobs = int(70 + coverage_ratio * 450)   # same count rule as the chunky mask

    mask_small = np.zeros((wh, ww), dtype=np.float32)
    for _ in range(n_blobs):
        anchor = anchors[rng.integers(0, len(anchors))]
        spread = diag * (0.15 + 0.55 * coverage_ratio)
        cy = float(np.clip(anchor[0] + rng.normal(0, spread), 0, wh - 1))
        cx = float(np.clip(anchor[1] + rng.normal(0, spread), 0, ww - 1))
        radius = diag * rng.uniform(*blob_size_range)
        max_r = radius * (1.0 + roughness)

        y0 = max(0, int(cy - max_r - 2))
        y1 = min(wh, int(cy + max_r + 2))
        x0 = max(0, int(cx - max_r - 2))
        x1 = min(ww, int(cx + max_r + 2))
        if y1 <= y0 or x1 <= x0:
            continue

        yy_l, xx_l = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        dy = yy_l - cy
        dx = xx_l - cx
        dist = np.sqrt(dy ** 2 + dx ** 2)
        theta = np.arctan2(dy, dx)
        wobble = 1.0 + roughness * (
            0.5 * np.sin(theta * 3 + rng.uniform(0, 6.28))
            + 0.3 * np.sin(theta * 7 + rng.uniform(0, 6.28))
            + 0.2 * np.sin(theta * 11 + rng.uniform(0, 6.28))
        )
        local_radius = radius * wobble
        blob = np.clip(1.0 - dist / (local_radius + 1e-6), 0, 1) ** 1.1   # falloff exponent
        mask_small[y0:y1, x0:x1] = np.maximum(mask_small[y0:y1, x0:x1], blob)

    mask_img = Image.fromarray((mask_small * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.0))
    mask_img = mask_img.resize((w, h), Image.BICUBIC)
    mask = np.asarray(mask_img).astype(np.float32) / 255.0

    texture = _sample_texture_patch(h, w, seed=seed)

    combined_alpha = mask * (1 - texture_strength + texture_strength * texture)
    combined_alpha = np.clip(combined_alpha, 0, 1)

    if ambient_brightness is None:
        ambient_brightness = float(image.mean())
    # Frost stays brighter than the scene by 2.3x or +90, whichever is larger,
    # so it remains visible on a dark frame.
    frost_tone = float(np.clip(max(ambient_brightness * 2.3, ambient_brightness + 90), 80, 250))
    tone_rgb = np.array(
        [frost_tone - 4, frost_tone - 1, min(frost_tone + 10, 255)], dtype=np.float32
    )

    opacity = float(np.clip(temperature_delta, 0, 1) * 0.95)
    alpha = (combined_alpha * opacity)[..., None]
    shade = 0.75 + 0.4 * texture
    frost_color = np.broadcast_to(tone_rgb, image.shape).astype(np.float32) * shade[..., None]

    out = image.astype(np.float32) * (1 - alpha) + frost_color * alpha
    return np.clip(out, 0, 255).astype(np.uint8)


def synthesize_night_frost_textured(image, exposure_ratio, coverage_ratio, temperature_delta,
                                     gamma=None, blur_strength=0.0, blur_fn=None,
                                     a=0.02, b=0.01, seed=None):
    """Low light plus textured frost: blur -> darken -> frost -> noise."""
    blur_fn = blur_fn or random_blur
    if gamma is None:
        gamma = np.random.uniform(0.8, 1.3)
    out = image
    if blur_strength > 0:
        out = blur_fn(out, strength_range=(blur_strength, blur_strength)) if blur_fn is random_blur else blur_fn(out, strength=blur_strength)
    dark = gamma_brightness(out, factor=exposure_ratio, gamma=gamma)
    frosted = generate_frost_overlay_textured(
        dark, coverage_ratio, temperature_delta,
        seed=seed, ambient_brightness=float(dark.mean())
    )
    noisy = poisson_gaussian_noise(frosted, a=a, b=b, seed=seed)
    return noisy



# Effects the S1-S5 recipes in scenarios.py call directly. Each takes its
# strength as an argument instead of drawing one, so a recipe stays reproducible.
def add_condensation(image, coverage_ratio, intensity, center=None, seed=None, work_size=800):
    """Condensation on the lens: a field of droplets that blurs and hazes what is behind it.

    `coverage_ratio` sets how wide the droplet field spreads, `intensity`
    how strongly it hazes, `center` where it sits (random middle 40% if None).
    Built on a `work_size` canvas and resized back, as in the chunky frost.
    """
    rng = _augmentation_rng(seed)
    h, w = image.shape[:2]

    scale = min(1.0, work_size / max(h, w))
    wh, ww = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
    small = cv2.resize(image, (ww, wh), interpolation=cv2.INTER_AREA)

    if center is None:
        cx0 = rng.integers(int(w * 0.3), int(w * 0.7))
        cy0 = rng.integers(int(h * 0.3), int(h * 0.7))
    else:
        cx0, cy0 = center
    cx, cy = cx0 * scale, cy0 * scale
    radius = coverage_ratio * min(wh, ww) * 0.6

    n_drops = int(30 + coverage_ratio * 150)
    mask = np.zeros((wh, ww), dtype=np.float32)
    for _ in range(n_drops):
        dx = rng.normal(0, radius * 0.5)
        dy = rng.normal(0, radius * 0.5)
        dr = rng.uniform(0.02, 0.06) * min(wh, ww)
        px, py = int(np.clip(cx + dx, 0, ww - 1)), int(np.clip(cy + dy, 0, wh - 1))
        y0, y1 = max(0, py - int(dr) - 2), min(wh, py + int(dr) + 2)
        x0, x1 = max(0, px - int(dr) - 2), min(ww, px + int(dr) + 2)
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        if yy.size == 0:
            continue
        dist = np.sqrt((yy - py) ** 2 + (xx - px) ** 2)
        drop = np.clip(1 - dist / (dr + 1e-6), 0, 1)
        mask[y0:y1, x0:x1] = np.maximum(mask[y0:y1, x0:x1], drop)

    sigma = min(wh, ww) * 0.04
    mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=sigma)
    if mask.max() > 1e-6:
        mask = mask / mask.max()
    blurred_small = cv2.GaussianBlur(small, (0, 0), sigmaX=sigma)

    haze_color = np.full_like(small, 235, dtype=np.float32)
    hazy_small = blurred_small.astype(np.float32) * 0.6 + haze_color * 0.4

    alpha = np.clip(mask * intensity * 1.8, 0, 1)[..., None]
    out_small = small.astype(np.float32) * (1 - alpha) + hazy_small * alpha
    out_small = np.clip(out_small, 0, 255).astype(np.uint8)

    return cv2.resize(out_small, (w, h), interpolation=cv2.INTER_CUBIC)


def add_glare(image, intensity, size_ratio, center=None, seed=None):
    """Add a circular highlight; radius = `size_ratio` x shorter side, falloff ^1.5."""
    rng = _augmentation_rng(seed)
    h, w = image.shape[:2]
    if center is None:
        center = (rng.integers(0, w), rng.integers(0, h))
    cx, cy = center
    radius = size_ratio * min(h, w)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    glare = np.clip(1 - dist / (radius + 1e-6), 0, 1) ** 1.5
    alpha = (glare * intensity)[..., None]
    highlight = np.full_like(image, 255, dtype=np.float32)
    out = image.astype(np.float32) * (1 - alpha) + highlight * alpha
    return np.clip(out, 0, 255).astype(np.uint8)


def color_jitter(image, brightness=0.5, contrast=0.4, saturation=0.3, hue=0.05):
    """Jitter brightness, contrast, saturation and hue by up to the given fractions."""
    return np.array(transforms.ColorJitter(brightness, contrast, saturation, hue)
                    (Image.fromarray(image)))


def add_gaussian_noise(image, sigma):
    """Add Gaussian noise of standard deviation `sigma`."""
    noise = np.random.normal(0, sigma, image.shape).astype(np.float32)
    return np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def adjust_gamma(image, gamma):
    """Gamma correction via a 256-entry LUT. `gamma` < 1 darkens."""
    inv = 1.0 / gamma
    table = ((np.arange(256) / 255.0) ** inv * 255).astype(np.uint8)
    return cv2.LUT(image, table)


def add_motion_blur(image, ksize, angle):
    """Directional blur: a 1-row kernel of size `ksize` rotated by `angle`."""
    kernel = np.zeros((ksize, ksize), dtype=np.float32)
    kernel[ksize // 2, :] = 1.0
    M = cv2.getRotationMatrix2D((ksize / 2, ksize / 2), angle, 1)
    kernel = cv2.warpAffine(kernel, M, (ksize, ksize))
    s = kernel.sum()
    if s > 0:
        kernel /= s
    return cv2.filter2D(image, -1, kernel)