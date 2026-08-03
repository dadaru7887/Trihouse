"""3온도 물류센터 카메라 도메인 변화 증강 후보 생성기.

각 원본 이미지와 증강 그룹마다 원본 1장 + 후보 8장을 저장하고,
검토용 3x3 비교판 PNG도 만든다. 화면 출력은 하지 않는다.
"""

import argparse
import gc
import random
from collections.abc import Callable
from pathlib import Path

import albumentations as A
import cv2
import matplotlib.pyplot as plt
import numpy as np
import torch
from PIL import Image
from torchvision import transforms


SEED = 42
GROUPS = (
    "opencv",
    "torchvision",
    "albumentations",
    "s2_condensation",
    "s3_glare",
    "s5_two_effects",
)
Recipe = tuple[str, Callable[[], np.ndarray]]


def preview_rgb(image_bgr: np.ndarray, max_width: int = 480) -> np.ndarray:
    """비교판에 넣을 축소 RGB 이미지. 개별 저장본은 축소하지 않는다."""
    height, width = image_bgr.shape[:2]
    if width > max_width:
        scale = max_width / width
        image_bgr = cv2.resize(image_bgr, (max_width, int(height * scale)))
    return cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)


def add_gaussian_noise(image_bgr: np.ndarray, sigma: float = 15) -> np.ndarray:
    """저조도에서 ISO/게인이 높아질 때의 센서 읽기 노이즈를 근사한다."""
    noise = np.random.normal(0, sigma, image_bgr.shape).astype(np.float32)
    return np.clip(image_bgr.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def adjust_gamma(image_bgr: np.ndarray, gamma: float = 0.7) -> np.ndarray:
    """어두운 저온 구역의 노출을 근사한다. gamma가 1보다 작으면 어두워진다."""
    table = np.array(
        [((value / 255.0) ** (1.0 / gamma)) * 255 for value in range(256)]
    ).astype(np.uint8)
    return cv2.LUT(image_bgr, table)


def add_motion_blur(image_bgr: np.ndarray, kernel_size: int, angle: float) -> np.ndarray:
    """로봇/카메라 이동 중 한 방향으로 번지는 모션 블러를 근사한다."""
    kernel = np.zeros((kernel_size, kernel_size), dtype=np.float32)
    center = kernel_size // 2
    cv2.line(kernel, (0, center), (kernel_size - 1, center), 1, 1)
    rotation = cv2.getRotationMatrix2D((center, center), angle, 1.0)
    kernel = cv2.warpAffine(kernel, rotation, (kernel_size, kernel_size))
    kernel /= kernel.sum()
    return cv2.filter2D(image_bgr, -1, kernel)


def add_glare(
    image_bgr: np.ndarray,
    strength: float = 0.55,
    radius_ratio: float = 0.22,
    center: tuple[int, int] | None = None,
) -> np.ndarray:
    """LED가 비닐 포장·금속·젖은 바닥·렌즈에 반사하는 하이라이트를 근사한다."""
    height, width = image_bgr.shape[:2]
    center = center or (int(width * 0.72), int(height * 0.25))
    x_grid, y_grid = np.meshgrid(np.arange(width), np.arange(height))
    distance = np.sqrt((x_grid - center[0]) ** 2 + (y_grid - center[1]) ** 2)
    sigma = radius_ratio * min(width, height)
    alpha = (strength * np.exp(-(distance**2) / (2 * sigma**2)))[..., None]
    result = image_bgr.astype(np.float32) * (1 - alpha) + 255 * alpha
    return np.clip(result, 0, 255).astype(np.uint8)


def add_condensation(
    image_bgr: np.ndarray,
    strength: float = 0.7,
    radius_ratio: float = 0.28,
    center: tuple[int, int] | None = None,
) -> np.ndarray:
    """저온 구역 진입 때 렌즈에 생기는 국소 결로/성에 의한 흐림을 근사한다."""
    height, width = image_bgr.shape[:2]
    center = center or (int(width * 0.50), int(height * 0.45))
    x_grid, y_grid = np.meshgrid(np.arange(width), np.arange(height))
    distance = np.sqrt((x_grid - center[0]) ** 2 + (y_grid - center[1]) ** 2)
    sigma = radius_ratio * min(width, height)
    mask = (strength * np.exp(-(distance**2) / (2 * sigma**2)))[..., None]
    blurred = cv2.GaussianBlur(image_bgr, (0, 0), sigmaX=12)
    result = image_bgr.astype(np.float32) * (1 - mask) + blurred.astype(np.float32) * mask
    haze = 0.15 * mask
    return np.clip(result * (1 - haze) + 245 * haze, 0, 255).astype(np.uint8)


def torch_recipe(
    original_bgr: np.ndarray, transform: Callable, seed: int
) -> Callable[[], np.ndarray]:
    """Torchvision 변환을 BGR 입력/출력 recipe로 감싼다."""
    original_pil = Image.fromarray(cv2.cvtColor(original_bgr, cv2.COLOR_BGR2RGB))

    def apply() -> np.ndarray:
        torch.manual_seed(seed)
        return cv2.cvtColor(np.array(transform(original_pil)), cv2.COLOR_RGB2BGR)

    return apply


def albu_recipe(
    original_bgr: np.ndarray, transform: A.BasicTransform, seed: int
) -> Callable[[], np.ndarray]:
    """Albumentations 단일 변환을 재현 가능한 recipe로 감싼다."""
    return lambda: A.Compose([transform], seed=seed)(image=original_bgr)["image"]


def build_recipes(original_bgr: np.ndarray, seed: int) -> dict[str, list[Recipe]]:
    """각 라이브러리/시나리오별 후보 8개를 만든다."""
    height, width = original_bgr.shape[:2]

    return {
        "opencv": [
            ("noise_mild_sigma8", lambda: add_gaussian_noise(original_bgr, 8)),
            ("noise_strong_sigma25", lambda: add_gaussian_noise(original_bgr, 25)),
            ("low_light_mild_gamma085", lambda: adjust_gamma(original_bgr, 0.85)),
            ("low_light_strong_gamma055", lambda: adjust_gamma(original_bgr, 0.55)),
            ("motion_blur_short", lambda: add_motion_blur(original_bgr, 9, 18)),
            ("motion_blur_long", lambda: add_motion_blur(original_bgr, 25, 18)),
            ("gaussian_blur", lambda: cv2.GaussianBlur(original_bgr, (0, 0), 1.4)),
            ("low_contrast", lambda: cv2.convertScaleAbs(original_bgr, alpha=0.72, beta=36)),
        ],
        "torchvision": [
            ("color_jitter_mild", torch_recipe(original_bgr, transforms.ColorJitter(0.15, 0.10, 0.05), seed + 1)),
            ("color_jitter_wide", torch_recipe(original_bgr, transforms.ColorJitter(0.35, 0.25, 0.15), seed + 2)),
            ("gaussian_blur_mild", torch_recipe(original_bgr, transforms.GaussianBlur(5, (0.3, 0.7)), seed + 3)),
            ("gaussian_blur_strong", torch_recipe(original_bgr, transforms.GaussianBlur(13, (1.2, 2.2)), seed + 4)),
            ("jitter_plus_blur", torch_recipe(original_bgr, transforms.Compose([transforms.ColorJitter(0.30, 0.20, 0.10), transforms.GaussianBlur(9, (0.4, 1.2))]), seed + 5)),
            ("auto_contrast", torch_recipe(original_bgr, transforms.RandomAutocontrast(p=1.0), seed + 6)),
            ("adjust_sharpness", torch_recipe(original_bgr, transforms.RandomAdjustSharpness(1.5, p=1.0), seed + 7)),
            ("posterize_5bits", torch_recipe(original_bgr, transforms.RandomPosterize(5, p=1.0), seed + 8)),
        ],
        "albumentations": [
            ("brightness_contrast", albu_recipe(original_bgr, A.RandomBrightnessContrast(brightness_limit=(-0.35, 0.15), contrast_limit=(-0.15, 0.20), p=1.0), seed + 1)),
            ("gamma_low_light", albu_recipe(original_bgr, A.RandomGamma(gamma_limit=(120, 150), p=1.0), seed + 2)),
            ("gauss_noise", albu_recipe(original_bgr, A.GaussNoise(std_range=(0.01, 0.04), p=1.0), seed + 3)),
            ("iso_noise", albu_recipe(original_bgr, A.ISONoise(color_shift=(0.01, 0.03), intensity=(0.15, 0.35), p=1.0), seed + 4)),
            ("motion_blur", albu_recipe(original_bgr, A.MotionBlur(blur_limit=(7, 13), p=1.0), seed + 5)),
            ("gaussian_blur", albu_recipe(original_bgr, A.GaussianBlur(blur_limit=(5, 11), sigma_limit=(0.8, 2.0), p=1.0), seed + 6)),
            ("image_compression", albu_recipe(original_bgr, A.ImageCompression(compression_type="jpeg", quality_range=(25, 50), p=1.0), seed + 7)),
            ("uniform_haze_fog", albu_recipe(original_bgr, A.RandomFog(fog_coef_range=(0.15, 0.30), alpha_coef=0.08, p=1.0), seed + 8)),
        ],
        "s2_condensation": [
            ("center_mild", lambda: add_condensation(original_bgr, 0.35, 0.18)),
            ("center_medium", lambda: add_condensation(original_bgr, 0.60, 0.28)),
            ("center_strong", lambda: add_condensation(original_bgr, 0.80, 0.34)),
            ("left_edge", lambda: add_condensation(original_bgr, 0.60, 0.26, (int(width * 0.18), int(height * 0.45)))),
            ("right_edge", lambda: add_condensation(original_bgr, 0.60, 0.26, (int(width * 0.82), int(height * 0.45)))),
            ("top_edge", lambda: add_condensation(original_bgr, 0.55, 0.24, (int(width * 0.50), int(height * 0.12)))),
            ("bottom_edge", lambda: add_condensation(original_bgr, 0.55, 0.24, (int(width * 0.50), int(height * 0.88)))),
            ("wide_haze", lambda: add_condensation(original_bgr, 0.42, 0.48)),
        ],
        "s3_glare": [
            ("small_mild", lambda: add_glare(original_bgr, 0.25, 0.10)),
            ("small_strong", lambda: add_glare(original_bgr, 0.75, 0.10)),
            ("wide_soft", lambda: add_glare(original_bgr, 0.35, 0.34)),
            ("wide_strong", lambda: add_glare(original_bgr, 0.65, 0.30)),
            ("upper_left", lambda: add_glare(original_bgr, 0.55, 0.18, (int(width * 0.20), int(height * 0.20)))),
            ("upper_right", lambda: add_glare(original_bgr, 0.55, 0.18, (int(width * 0.80), int(height * 0.20)))),
            ("floor_left", lambda: add_glare(original_bgr, 0.45, 0.20, (int(width * 0.25), int(height * 0.78)))),
            ("floor_right", lambda: add_glare(original_bgr, 0.45, 0.20, (int(width * 0.75), int(height * 0.78)))),
        ],
        "s5_two_effects": [
            ("condensation_mild_plus_low_light", lambda: adjust_gamma(add_condensation(original_bgr, 0.40, 0.22), 0.80)),
            ("condensation_medium_plus_low_light", lambda: adjust_gamma(add_condensation(original_bgr, 0.65, 0.30), 0.68)),
            ("edge_condensation_plus_low_light", lambda: adjust_gamma(add_condensation(original_bgr, 0.60, 0.25, (int(width * 0.18), int(height * 0.45))), 0.72)),
            ("condensation_plus_noise", lambda: add_gaussian_noise(add_condensation(original_bgr, 0.55, 0.26), 12)),
            ("condensation_plus_motion_blur", lambda: add_motion_blur(add_condensation(original_bgr, 0.52, 0.24), 13, 18)),
            ("glare_plus_low_light", lambda: adjust_gamma(add_glare(original_bgr, 0.48, 0.20), 0.72)),
            ("glare_plus_noise", lambda: add_gaussian_noise(add_glare(original_bgr, 0.48, 0.18), 12)),
            ("low_light_plus_motion_blur", lambda: add_motion_blur(adjust_gamma(original_bgr, 0.65), 15, 18)),
        ],
    }


def save_candidate_group(
    target_stem: str,
    original_bgr: np.ndarray,
    group_name: str,
    recipes: list[Recipe],
    candidate_root: Path,
    comparison_root: Path,
) -> Path:
    """개별 후보 9개와 여백을 줄인 3x3 비교판 한 장을 저장한다."""
    if len(recipes) != 8:
        raise ValueError(f"{group_name}: 원본 외 후보는 8개여야 합니다.")

    group_dir = candidate_root / target_stem / group_name
    group_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(group_dir / "00_original.png"), original_bgr)
    previews = [("original", preview_rgb(original_bgr))]

    for index, (name, recipe) in enumerate(recipes, start=1):
        image_bgr = recipe()
        cv2.imwrite(str(group_dir / f"{index:02d}_{name}.png"), image_bgr)
        previews.append((name, preview_rgb(image_bgr)))
        del image_bgr
        gc.collect()

    fig, axes = plt.subplots(3, 3, figsize=(12, 13))
    for axis, (name, preview) in zip(axes.ravel(), previews):
        axis.imshow(preview)
        axis.set_title(name, fontsize=10)
        axis.axis("off")
    fig.suptitle(f"{target_stem} | {group_name} | original + 8 candidates", fontsize=15)
    fig.subplots_adjust(left=0.02, right=0.98, bottom=0.02, top=0.92, wspace=0.02, hspace=0.08)

    comparison_root.mkdir(parents=True, exist_ok=True)
    grid_path = comparison_root / f"{target_stem}__{group_name}_comparison.png"
    fig.savefig(grid_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    del previews
    gc.collect()
    return grid_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stems",
        nargs="+",
        default=["all"],
        help="처리할 파일 stem. 기본값 all. 예: --stems pinky-pro_0 pinky-pro_2",
    )
    parser.add_argument(
        "--groups",
        nargs="+",
        choices=(*GROUPS, "all"),
        default=["all"],
        help="처리할 증강 그룹. 기본값 all.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Trihouse 프로젝트 루트 경로. 생략하면 이 파일 위치를 기준으로 자동 설정.",
    )
    parser.add_argument("--seed", type=int, default=SEED, help="재현성 시드")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    raw_dir = project_root / "dataset" / "raw_examples"
    output_dir = Path(__file__).resolve().parent / "previews"
    candidate_root = output_dir / "candidate_variants"
    comparison_root = output_dir / "library_comparisons"

    available_paths = sorted(raw_dir.glob("*.png"))
    if not available_paths:
        raise FileNotFoundError(f"PNG 원본이 없습니다: {raw_dir}")

    available_by_stem = {path.stem: path for path in available_paths}
    selected_paths = available_paths if args.stems == ["all"] else []
    if not selected_paths:
        missing = [stem for stem in args.stems if stem not in available_by_stem]
        if missing:
            raise ValueError(f"없는 TARGET_STEM: {', '.join(missing)}")
        selected_paths = [available_by_stem[stem] for stem in args.stems]

    selected_groups = list(GROUPS) if args.groups == ["all"] else args.groups
    for image_index, image_path in enumerate(selected_paths):
        original_bgr = cv2.imread(str(image_path))
        if original_bgr is None:
            print(f"건너뜀: 읽을 수 없음 - {image_path}")
            continue

        print(f"\n[{image_path.stem}] {len(selected_groups)}개 그룹 생성")
        recipes_by_group = build_recipes(original_bgr, args.seed + image_index * 100)
        for group_name in selected_groups:
            grid_path = save_candidate_group(
                image_path.stem,
                original_bgr,
                group_name,
                recipes_by_group[group_name],
                candidate_root,
                comparison_root,
            )
            print(f"  저장: {grid_path.relative_to(output_dir)}")
            gc.collect()


if __name__ == "__main__":
    main()
