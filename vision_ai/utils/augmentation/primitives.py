"""환경 열화의 원시 연산 — 저조도·블러·노이즈·결로·글레어·성에.

## 이 파일이 하는 일

다온도 창고(상온 15~25 °C / 냉장 0~5 °C / 냉동 -25~-18 °C)를 오가는 로봇 카메라에
실제로 생기는 광학 열화를 이미지 위에 합성한다. 회전·크롭 같은 기하 증강이 아니라
**광학(photometric) 증강**이라, 마스크·라벨은 그대로 두고 그림만 바꾼다.

여기에는 시나리오에 매이지 않은 **재사용 가능한 조각**만 둔다. 어떤 조각을 어떤
세기로 어떻게 조합해 S1~S5 를 만드는지는 상위 모듈이 정한다:
`vision_ai/models/perception/trainer/augmentation_recipes.py`.

## 어떻게 불리는가

직접 실행하는 파일이 아니다. 학습 중에만, 아래 경로로 간접 호출된다.

    vision_ai.main train --model perception --stage segmentation --data <data.yaml>
      -> trainer/yoloe_trainer.py  (importlib 로 recipes 적재)
        -> trainer/augmentation_recipes.py  mixed_augmentation()
          -> 이 파일의 함수들

## 함수 묶음

| 묶음 | 함수 | 만드는 열화 |
| --- | --- | --- |
| 밝기 | `gamma_brightness` `adjust_gamma` `synthesize_low_light` | 저조도, 감마 |
| 노이즈 | `poisson_gaussian_noise` `add_gaussian_noise` | 센서 노이즈 |
| 블러 | `gaussian_blur` `disc_blur` `motion_blur` `edge_blur` `random_blur` `add_motion_blur` | 흔들림, 초점 |
| 결로 | `add_condensation` | 온도차로 렌즈에 맺힌 물방울 |
| 글레어 | `add_glare` | 조명·반사면 |
| 성에 | `generate_frost_overlay_*` `synthesize_night_frost_*` | 냉동 구역 렌즈 서리 |

## 난수

세기와 위치는 `rng.augmentation_rng()` 가 준 독립 RNG 에서 뽑는다. 학습 난수열을
소비하지 않기 위해서다 — 근거는 `rng.py` 상단에 있다.

원본: `Data_Aug_Test_Combined_merged.ipynb` / `train_yoloe.ipynb`.
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

# ============================================================
# 1. 핵심 증강 함수 (Data_Aug_Test_Combined_merged.ipynb 그대로)
# ============================================================
# ── 2. 핵심 증강 함수 ─────────────────────────────────────

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
    '''저조도만 단독으로 쓸 때: 어둡게 + 센서노이즈. gamma를 같이 주면 단순히
    밝기만 낮추는 게 아니라 톤 커브 자체가 달라져서 "어둡다"의 양상이 다양해짐
    (예: 그림자만 깊어지는 느낌 vs 전체적으로 뿌옇게 어두워지는 느낌).
    (성에와 합칠 땐 이 함수 대신 synthesize_night_frost를 써서 노이즈를 성에
    합성 이후에 입히세요.)'''
    if exposure_ratio is None:
        exposure_ratio = np.random.uniform(0.15, 0.55)
    if gamma is None:
        gamma = np.random.uniform(0.8, 1.3)
    dark = gamma_brightness(image, factor=exposure_ratio, gamma=gamma)
    return poisson_gaussian_noise(dark, a=a, b=b, seed=seed)


# ── 블러 4종 (전부 해상도에 비례하게 설계 -> 고해상도 사진에서도 체감됨) ──

def gaussian_blur(image, strength=1.0):
    '''전반적으로 고르게 흐리게. 안개/습기 낀 대기 느낌.'''
    h, w = image.shape[:2]
    radius = max(1.0, min(h, w) * 0.006 * strength)
    return np.asarray(Image.fromarray(image).filter(ImageFilter.GaussianBlur(radius)))


def disc_blur(image, strength=1.0):
    '''원형(디스크) 커널 블러 -> 아웃포커스/보케 느낌. 렌즈에 김/성에 껴서
    초점이 안 맞을 때가 이 모양에 가까움.'''
    h, w = image.shape[:2]
    radius = max(2, int(min(h, w) * 0.008 * strength))
    yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    mask = (xx ** 2 + yy ** 2) <= radius ** 2
    kernel = mask.astype(np.float32)
    kernel /= kernel.sum()
    return cv2.filter2D(image, -1, kernel)


def motion_blur(image, strength=1.0, angle=None):
    '''특정 방향으로 쭉 늘어지는 블러. 카메라/로봇이 움직이는 동안 노출됐을 때.'''
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
    '''중심은 선명하고 가장자리로 갈수록 흐려짐 (렌즈 주변부 화질저하 느낌).
    성에의 edge_bias 패턴과 같은 논리라 성에와 같이 쓰면 자연스럽게 붙음.'''
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
    '''매번 블러 타입 중 하나를 무작위로 골라서 적용.
    기본은 disc(보케)/motion(움직임) 두 가지만 씀 -- edge/gaussian은 실전감이
    떨어져서 기본 후보에서 제외 (types로 직접 지정하면 다른 것도 쓸 수 있음).'''
    types = types or ["disc", "motion"]
    choice = np.random.choice(types)
    strength = np.random.uniform(*strength_range)
    return BLUR_FUNCS[choice](image, strength=strength)


# scaled_blur이라는 이름으로도 예전 코드와 호환되게 유지 (gaussian_blur의 별칭)
def scaled_blur(image, strength=1.0):
    """Alias for `gaussian_blur`, kept for a uniform strength argument."""
    return gaussian_blur(image, strength=strength)


def generate_frost_overlay_v3(image, coverage_ratio, temperature_delta, seed=None,
                               n_octaves=4, edge_bias=1.8, ambient_brightness=None,
                               n_anchors=None):
    '''노이즈 업스케일링 기반 성에 (v4 개선).
    - 비대칭 성장: 화면 중앙 기준 방사형 대신, 1~2개의 무작위 모서리(코너)에서부터
      진해지는 구조라 실제 서리처럼 한쪽으로 삐뚤빼뚤 자란 모양이 됨.
    - 결정(vein) 텍스처: 능선 모양 노이즈를 곱해서 뭉게구름 대신 가늘게 뻗은
      결정/깃털 무늬가 섞이도록 함.
    - 살짝 푸르스름한 흰색 톤 (순수 회색이 아니라 R,G 약간 낮추고 B를 올림).
    - frost_color는 ambient_brightness(장면 평균 밝기)에 맞춰 정해서, 어두운
      장면에서는 성에도 칙칙하게 나오도록 함.
    '''
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

    # 결정(vein) 텍스처: 능선 모양 노이즈(1 - |2x-1|)를 세제곱해서 뾰족한 무늬로 만들고 곱해줌
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

    # 비대칭 성장: 화면 중앙이 아니라 1~2개의 무작위 모서리에서부터 진해짐
    if n_anchors is None:
        n_anchors = int(rng.integers(1, 3))
    corners = np.array([[0, 0], [0, w], [h, 0], [h, w]], dtype=np.float32)
    anchor_idx = rng.choice(4, size=n_anchors, replace=False)
    anchors = corners[anchor_idx]

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    diag = float(np.sqrt(h ** 2 + w ** 2))
    anchor_bias = np.ones((h, w), dtype=np.float32)
    denom = 0.55 * diag  # 이 거리 안쪽에서 성에 농도가 1에 도달 (작을수록 코너 쪽에 더 몰림)
    for ay, ax in anchors:
        dist = np.sqrt((yy - ay) ** 2 + (xx - ax) ** 2) / denom
        anchor_bias = np.minimum(anchor_bias, dist)
    anchor_bias = np.clip(anchor_bias ** (edge_bias * 0.55), 0, 1)
    combined = combined * (0.35 + 0.65 * anchor_bias)

    threshold = 1.0 - coverage_ratio
    frost = np.clip((combined - threshold) / (1 - threshold + 1e-6), 0, 1)
    # 완전히 뒤덮인(포화된) 영역도 밋밋한 흰 덩어리로 안 보이게 vein 텍스처를 한 번 더 곱함
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
    '''저조도 + 성에를 물리적으로 맞는 순서로 합침.
    순서: 블러 -> 노출 감소(암부, gamma로 톤 커브까지 다양화) -> 성에 합성(암부 밝기에 맞춘 톤)
    -> 센서노이즈(마지막, 전체 균일)
    blur_fn을 안 주면 random_blur를 써서 매번 다른 블러 모양이 나오게 함.'''
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
    '''냉동/냉장 창고에서 실제로 보이는 "두툼하고 울퉁불퉁하게 뭉친" 성에를 모사.
    v3(유리창 성에, 가는 결정/양치식물 무늬)와는 다른 종류 -- 이건 렌즈에 눈/성에
    덩어리가 겹겹이 쌓이는 형태라, PDF에서 말한 "빗방울 생성 알고리즘 기반"과
    같은 원리로 구현: 울퉁불퉁한 경계를 가진 덩어리(blob)를 여러 개 겹쳐 쌓음.

    work_size: 실제 마스크 연산은 이 크기(짧은 변 기준)로 축소해서 계산한 뒤
    원본 해상도로 다시 확대함. 블롭 개수/크기가 이미지 크기에 비례하므로 고해상도
    사진(4000px+)에서 그대로 계산하면 매우 느려짐 -> 작은 캔버스에서 계산 후
    업샘플하면 수십 배 빨라지고 육안상 차이는 거의 없음.
    '''
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
        n_blobs = int(70 + coverage_ratio * 450)  # 기존보다 훨씬 촘촘하게

    mask = np.zeros((wh, ww), dtype=np.float32)
    h, w = wh, ww  # 이하 블롭 루프는 축소된 캔버스 기준으로 계산

    for _ in range(n_blobs):
        anchor = anchors[rng.integers(0, len(anchors))]
        spread = diag * (0.15 + 0.55 * coverage_ratio)
        cy = float(np.clip(anchor[0] + rng.normal(0, spread), 0, h - 1))
        cx = float(np.clip(anchor[1] + rng.normal(0, spread), 0, w - 1))
        radius = diag * rng.uniform(*blob_size_range)
        max_r = radius * (1.0 + roughness)  # wobble로 커질 수 있는 최대 반경

        # 성능 최적화: 이미지 전체가 아니라 덩어리 주변 bounding box만 계산
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
        # 원이 아니라 각도별로 반지름이 흔들리게 -> 울퉁불퉁한 덩어리 경계
        wobble = 1.0 + roughness * (
            0.5 * np.sin(theta * 3 + rng.uniform(0, 6.28))
            + 0.3 * np.sin(theta * 7 + rng.uniform(0, 6.28))
            + 0.2 * np.sin(theta * 11 + rng.uniform(0, 6.28))
        )
        local_radius = radius * wobble
        blob = np.clip(1.0 - dist / (local_radius + 1e-6), 0, 1)
        blob = blob ** 1.1  # 1.5 -> 1.1 : 가장자리가 너무 급하게 옅어지지 않게
        mask[y0:y1, x0:x1] = np.maximum(mask[y0:y1, x0:x1], blob)

    mask_img = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.0))
    # 축소 캔버스에서 계산한 마스크를 원본 해상도로 업샘플
    orig_h, orig_w = image.shape[:2]
    mask_img = mask_img.resize((orig_w, orig_h), Image.BICUBIC)
    mask = np.asarray(mask_img).astype(np.float32) / 255.0

    if ambient_brightness is None:
        ambient_brightness = float(image.mean())
    # 어두운 장면일수록 성에도 같이 어두워지면 대비가 사라지므로, 절대적으로 확실한
    # 밝기 차이(배율 2.3배 또는 최소 +90 중 큰 쪽)를 보장 -> 어떤 밝기에서도 눈에 띄게 함
    frost_tone = float(np.clip(max(ambient_brightness * 2.3, ambient_brightness + 90), 80, 250))
    tone_rgb = np.array(
        [frost_tone - 4, frost_tone - 1, min(frost_tone + 10, 255)], dtype=np.float32
    )

    opacity = float(np.clip(temperature_delta, 0, 1) * 0.95)
    alpha = (mask * opacity)[..., None]
    frost_color = np.broadcast_to(tone_rgb, image.shape).astype(np.float32)
    # 덩어리 내부에도 밝기 요철(울퉁불퉁한 입체감)을 살짝 반영
    shade = 0.85 + 0.15 * mask
    frost_color = frost_color * shade[..., None]

    out = image.astype(np.float32) * (1 - alpha) + frost_color * alpha
    return np.clip(out, 0, 255).astype(np.uint8)


def synthesize_night_frost_chunky(image, exposure_ratio, coverage_ratio, temperature_delta,
                                   gamma=None, blur_strength=0.0, blur_fn=None,
                                   n_blobs=None, blob_size_range=(0.03, 0.12), roughness=0.35,
                                   a=0.02, b=0.01, seed=None):
    '''chunky(냉동고) 성에 버전의 야간 성에 합성. 순서는 night_frost와 동일:
    블러 -> 암부 -> 성에 -> 노이즈.
    n_blobs를 직접 지정하면 자동 계산값 대신 그 개수를 씀 (더 촘촘하게 끼우고 싶을 때).'''
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


# ── 실사 텍스처 블렌딩 성에 ────────────────────────────────
# 무료(Unsplash License, 별도 출처표기 불필요) 성에/얼음 매크로사진.
# 모양/커버리지는 우리 procedural 마스크가 제어하고, 결정 디테일만 실사에서 가져옴.
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
    '''실사 텍스처에서 (h,w) 크기의 디테일 패치를 뽑아 0~1로 정규화해서 반환.
    2x2 미러 타일링으로 이음새를 줄이고, 랜덤 크롭+스케일로 매번 다르게 보이게 함.'''
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
    '''chunky 마스크(모양/커버리지 제어) + 실사 성에 텍스처(결정 디테일)를 합성.
    모양은 procedural로 계속 제어하고, 안쪽 결의 디테일만 실제 성에 매크로사진에서
    가져와서 노이즈 기반보다 훨씬 자연스러운 결정 무늬가 나오게 함.'''
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
        n_blobs = int(70 + coverage_ratio * 450)  # 기존보다 훨씬 촘촘하게

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
        blob = np.clip(1.0 - dist / (local_radius + 1e-6), 0, 1) ** 1.1  # 1.5 -> 1.1
        mask_small[y0:y1, x0:x1] = np.maximum(mask_small[y0:y1, x0:x1], blob)

    mask_img = Image.fromarray((mask_small * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.0))
    mask_img = mask_img.resize((w, h), Image.BICUBIC)
    mask = np.asarray(mask_img).astype(np.float32) / 255.0

    texture = _sample_texture_patch(h, w, seed=seed)

    combined_alpha = mask * (1 - texture_strength + texture_strength * texture)
    combined_alpha = np.clip(combined_alpha, 0, 1)

    if ambient_brightness is None:
        ambient_brightness = float(image.mean())
    # 어두운 장면일수록 성에도 같이 어두워지면 대비가 사라지므로, 절대적으로 확실한
    # 밝기 차이(배율 2.3배 또는 최소 +90 중 큰 쪽)를 보장 -> 어떤 밝기에서도 눈에 띄게 함
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
    '''textured(실사 텍스처) 성에 버전의 야간 성에 합성.'''
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

print("핵심 함수 정의 완료")


# ============================================================
# 2. S1~S5 헬퍼 함수
# ============================================================
# ── S1~S5 후보군 튜닝에서 썼던 헬퍼 함수들 (add_condensation 등) ──
def add_condensation(image, coverage_ratio, intensity, center=None, seed=None, work_size=800):
    '''렌즈에 맺힌 결로(물방울) 모사. 축소 캔버스에서 계산(work_size 트릭, 고해상도에서 빠름) +
    블러 후 mask 정규화(피크값 복원) + haze 블렌딩까지 반영된 최종 버전.'''
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


print("S1~S5용 헬퍼 함수 정의 완료")


