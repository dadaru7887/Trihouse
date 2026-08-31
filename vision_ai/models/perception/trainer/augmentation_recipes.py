#!/usr/bin/env python3
"""
YOLOE 세그멘테이션 학습 스크립트 -- 온라인 증강(S1~S5 다 섞기) ON/OFF 지원.

사용 예:
    python train.py --model yoloe --augmentation true  --data /path/to/data.yaml
    python train.py --model yoloe --augmentation false --data /path/to/data.yaml --epochs 100

증강 관련 코드(핵심 함수 / S1~S5 헬퍼 / MIXED_POOL)는
Data_Aug_Test_Combined_merged.ipynb / train_yoloe.ipynb에서 그대로 옮겨왔습니다.
"""

import argparse
import os
import random

import albumentations as A
import numpy as np
import torch
from datetime import datetime, timedelta, timezone
from PIL import Image
from torchvision import transforms

from vision_ai.utils.augmentation.primitives import (
    add_condensation, add_glare, add_motion_blur, adjust_gamma,
    generate_frost_overlay_chunky, synthesize_night_frost_chunky,
)
from vision_ai.utils.augmentation.rng import (
    configure_augmentation_seed, isolated_augmentation_random_state,
)

# 증강 전용 난수 스트림의 기본 seed.
#
# **여기서 전역 RNG(random / np.random / torch)를 건드리지 않는다.** 예전에는
# 이 자리에서 세 개를 전부 seed(42) 로 고정했는데, `yoloe_trainer.train()` 이
# `seed_everything(config.seed)` **직후에** 이 모듈을 import 하므로 사용자가 준
# --seed 가 그 자리에서 42 로 덮였다. 예외가 아니라 "재현이 안 된다" 로만
# 나타나서 원인에서 가장 먼 버그였다.
#
# 학습 seed 는 호출부(`utils/reproducibility.seed_everything`)가, 증강 seed 는

KST = timezone(timedelta(hours=9))  # zoneinfo 대신 고정 오프셋 -- 도커 슬림 이미지엔 tzdata가 없을 수 있음

# ============================================================
# 3. S1~S5 다 섞기 (mixed_augmentation)
# ============================================================
# ── S1~S5 튜닝 결과를 하나의 풀(pool)로 섞기 ──
# 지금까지 candidate-group에서 눈으로 확정한 값들을 그대로 가져와서,
# 매 학습 스텝마다 이 풀에서 하나를 무작위로 뽑아 적용합니다.
# (전부 RGB 이미지 기준 -- 학습 파이프라인이 RGB라서 candidate-group 셀과 달리 BGR 변환 없음)

def _s1_gamma(image):
    gamma = random.uniform(0.55, 0.65)  # 확정한 mild(0.65)~strong(0.55) 범위
    return adjust_gamma(image, gamma)


def _s1_motion_blur(image):
    ksize = random.choice([45, 70])
    return add_motion_blur(image, ksize, 18)  # 홀수 보정 불필요, 그대로 45/70 사용


def _s1_color_jitter(image):
    pil_img = Image.fromarray(image)
    jitter = transforms.ColorJitter(0.5, 0.4, 0.3, 0.05)  # 확정한 wide 설정
    return np.array(jitter(pil_img))


def _s2_condensation(image):
    h, w = image.shape[:2]
    recipe = random.choice([
        (0.35, 0.18, None),
        (0.80, 0.34, None),
        (0.55, 0.24, (int(w * 0.50), int(h * 0.12))),   # top_edge
        (0.55, 0.24, (int(w * 0.50), int(h * 0.88))),   # bottom_edge
        (0.42, 0.48, None),                              # wide_haze
    ])
    coverage, intensity, center = recipe
    return add_condensation(image, coverage, intensity, center)


def _s3_glare(image):
    h, w = image.shape[:2]
    recipe = random.choice([
        (0.65, 0.30, None),
        (0.45, 0.25, (int(w * 0.5), int(h * 0.30))),   # ceiling_near_mild
        (0.70, 0.45, (int(w * 0.5), int(h * 0.30))),   # ceiling_near_strong
        (0.40, 0.30, (int(w * 0.5), int(h * 0.85))),   # floor_near_mild
        (0.65, 0.55, (int(w * 0.5), int(h * 0.85))),   # floor_near_strong
    ])
    intensity, size_ratio, center = recipe
    return add_glare(image, intensity, size_ratio, center)


def _s4_frost(image):
    coverage, temperature = random.choice([(0.15, 0.30), (0.45, 0.55)])
    return generate_frost_overlay_chunky(image, coverage, temperature, seed=None, n_anchors=4)


def _s4_night_frost(image):
    exposure, coverage, temperature, blur_strength = random.choice([
        (0.45, 0.35, 0.45, 1.0),   # night_light
        (0.60, 0.35, 0.45, 1.3),   # night_heavy
    ])
    return synthesize_night_frost_chunky(
        image, exposure_ratio=exposure, coverage_ratio=coverage,
        temperature_delta=temperature, blur_strength=blur_strength,
    )


# S5: 확정한 5가지 조합(mild/strong) -- Motion Blur는 항상 마지막
def _s5_lowlight_condensation(image):
    if random.random() < 0.5:
        return add_motion_blur(add_condensation(adjust_gamma(image, 0.65), 0.35, 0.18), 45, 18)
    return add_motion_blur(add_condensation(adjust_gamma(image, 0.55), 0.80, 0.34), 70, 18)


def _s5_lowlight_glare(image):
    h, w = image.shape[:2]
    if random.random() < 0.5:
        return add_motion_blur(
            add_glare(adjust_gamma(image, 0.65), 0.45, 0.25, (int(w * 0.5), int(h * 0.30))), 45, 18)
    return add_motion_blur(
        add_glare(adjust_gamma(image, 0.55), 0.65, 0.55, (int(w * 0.5), int(h * 0.85))), 70, 18)


def _s5_condensation_glare(image):
    h, w = image.shape[:2]
    if random.random() < 0.5:
        return add_motion_blur(
            add_glare(add_condensation(image, 0.55, 0.24, (int(w * 0.5), int(h * 0.12))),
                      0.45, 0.25, (int(w * 0.5), int(h * 0.30))), 45, 18)
    return add_motion_blur(
        add_glare(add_condensation(image, 0.42, 0.48),
                  0.65, 0.55, (int(w * 0.5), int(h * 0.85))), 70, 18)


def _s5_lowlight_frost(image):
    if random.random() < 0.5:
        frosted = generate_frost_overlay_chunky(adjust_gamma(image, 0.65), 0.15, 0.30, seed=None, n_anchors=4)
        return add_motion_blur(frosted, 45, 18)
    frosted = generate_frost_overlay_chunky(adjust_gamma(image, 0.55), 0.45, 0.55, seed=None, n_anchors=4)
    return add_motion_blur(frosted, 70, 18)


def _s5_frost_glare(image):
    h, w = image.shape[:2]
    if random.random() < 0.5:
        frosted = generate_frost_overlay_chunky(image, 0.15, 0.30, seed=None, n_anchors=4)
        return add_motion_blur(add_glare(frosted, 0.45, 0.25, (int(w * 0.5), int(h * 0.30))), 45, 18)
    frosted = generate_frost_overlay_chunky(image, 0.45, 0.55, seed=None, n_anchors=4)
    return add_motion_blur(add_glare(frosted, 0.65, 0.55, (int(w * 0.5), int(h * 0.85))), 70, 18)


# ── 전체 풀: S1~S5 다 섞기 ──
MIXED_POOL = [
    _s1_gamma, _s1_motion_blur, _s1_color_jitter,          # S1
    _s2_condensation,                                       # S2
    _s3_glare,                                               # S3
    _s4_frost, _s4_night_frost,                              # S4
    _s5_lowlight_condensation, _s5_lowlight_glare,           # S5
    _s5_condensation_glare, _s5_lowlight_frost, _s5_frost_glare,
]


def mixed_augmentation(image, **kwargs):
    '''S1~S5 풀에서 매번 하나를 무작위로 골라 적용.'''
    with isolated_augmentation_random_state():
        fn = random.choice(MIXED_POOL)
        return fn(image)


print(f"MIXED_POOL 구성 완료: 총 {len(MIXED_POOL)}개 증강 함수 (S1~S5 전부 포함)")


# ============================================================
# 4. CLI
# ============================================================

def parse_args():
    p = argparse.ArgumentParser(
        description="YOLOE segmentation training with online S1-S5 augmentation (GPU)")
    p.add_argument("--model", type=str, default="yoloe-26s-seg.pt",
                   help="Weight filename or path. Shorthands are not expanded, so write "
                        "the name that is actually used (e.g. yoloe-26s-seg.pt)")
    p.add_argument("--augmentation", action=argparse.BooleanOptionalAction, default=True,
                   help="Online S1-S5 augmentation. Pass --no-augmentation to disable")
    p.add_argument("--data", type=str, required=True,
                   help="Path to data.yaml")
    p.add_argument("--imgsz", type=int, default=640,
                   help="Training image size in pixels")
    p.add_argument("--augmentation-seed", type=int, default=42,
                   help="Seed for the augmentation RNG only, independent of the training seed")
    p.add_argument("--seed", type=int, default=42,
                   help="Training seed")
    p.add_argument("--epochs", type=int, default=200,
                   help="Upper bound is generous because patience-based early stopping ends the run")
    p.add_argument("--patience", type=int, default=20,
                   help="Stop early when validation has not improved for this many epochs")
    p.add_argument("--batch", type=str, default="-1",
                   help="Batch size. -1 lets ultralytics auto-batch target roughly 60%% of GPU memory")
    p.add_argument("--device", type=str, default="0",
                   help="GPU index (e.g. 0, or 0,1) or cpu")
    p.add_argument("--workers", type=int, default=8,
                   help="Dataloader workers. Lower this when the container --shm-size is small (e.g. 2)")
    p.add_argument("--project", type=str, default="runs/segment",
                   help="Parent directory for run output; relative paths are resolved from the "
                        "current working directory")
    p.add_argument("--name", type=str, default=None,
                   help="Run folder name. Defaults to <start time KST>_<model>_<aug|noaug>")
    return p.parse_args()


def main():
    args = parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    configure_augmentation_seed(args.augmentation_seed)

    use_augmentation = bool(args.augmentation)
    from vision_ai.models.perception.trainer.yoloe_trainer import resolve_model
    weight_path = resolve_model(args.model)
    batch = int(args.batch)  # -1 = auto
    project_dir = os.path.abspath(args.project)  # 실행 시점 작업 디렉토리 기준

    model_tag = os.path.splitext(os.path.basename(weight_path))[0]  # 예: yoloe-26s-seg
    aug_tag = "aug" if use_augmentation else "noaug"
    run_name = args.name or f"{datetime.now(KST):%Y%m%d_%H%M%S}_{model_tag}_{aug_tag}"

    # 무거운 ultralytics 임포트는 실제로 학습할 때만 (argparse --help가 빠르게 뜨게 하기 위함)
    from ultralytics import YOLOE
    from ultralytics.models.yolo.yoloe import YOLOEPESegTrainer

    if use_augmentation:
        online_transforms = [A.Lambda(image=mixed_augmentation, p=1.0, name="mixed_s1_s5")]
    else:
        online_transforms = []  # 빈 리스트 -> Ultralytics 기본 증강까지 완전히 비활성화

    print(f"[설정] model={weight_path} | augmentation={use_augmentation} | "
          f"transform 개수={len(online_transforms)} | data={args.data} | "
          f"device={args.device} | batch={batch} | imgsz={args.imgsz} | name={run_name}")

    def _set_augmentations(trainer):
        """on_pretrain_routine_start 콜백: 데이터로더가 만들어지기 전에 실행돼서,
        trainer.args.augmentations를 세팅하면 Ultralytics 내부 v8_transforms가
        Albumentations(transforms=hyp.augmentations)로 이 값을 그대로 사용하게 됨."""
        trainer.args.augmentations = online_transforms

    model = YOLOE(weight_path)
    model.add_callback("on_pretrain_routine_start", _set_augmentations)

    results = model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        patience=args.patience,
        batch=batch,
        device=args.device,
        workers=args.workers,
        project=project_dir,
        trainer=YOLOEPESegTrainer,
        name=run_name,
    )

    print("학습 결과 저장 경로:", results.save_dir)
    return results


if __name__ == "__main__":
    main()
