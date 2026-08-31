import argparse
from pathlib import Path

# 축약어를 쓰지 않는다. 여기 적힌 이름이 곧 ultralytics 가 찾는 파일명이다.
DEFAULT_MODEL = "yoloe-26s-seg.pt"

from vision_ai.utils.run_config import TrainingConfig


def add_training_arguments(parser: argparse.ArgumentParser, *, include_run: bool = True) -> None:
    parser.add_argument("--data", type=Path, required=True, help="YOLO segmentation data.yaml")
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help="가중치 파일명 또는 경로. 축약어를 확장하지 않으므로 실제로 쓰이는\n"
             "이름을 그대로 적는다 (예: yoloe-26s-seg.pt)",
    )
    parser.add_argument(
        "--augmentation", action=argparse.BooleanOptionalAction, default=True,
        help="Online augmentation from TRAIN_RECIPES. Disable with --no-augmentation",
    )
    parser.add_argument("--augmentation-seed", type=int, default=42)
    parser.add_argument(
        "--holdout", action="append", default=[],
        choices=("gamma", "motion_blur", "color_jitter", "condensation", "glare", "frost"),
        help="Degradation mechanism to keep out of training, for leave-one-out. "
             "Removes every recipe that can produce it. Repeatable",
    )
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--batch", type=int, default=-1)
    parser.add_argument("--device", default="auto",
                        help="auto (cuda > mps > cpu), cpu, mps, gpu/cuda or a GPU index")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--posture-manifest", type=Path)
    parser.add_argument(
        "--augmentation-source",
        type=Path,
        help="Drop-in replacement for the augmentation recipe module. "
             "Omit to use vision_ai/utils/augmentation/scenarios.py",
    )
    parser.add_argument("--allow-posture-gap", action="store_true")
    parser.add_argument("--wandb", action="store_true",
                        help="Mirror metrics to Weights & Biases. Falls back to "
                             "metrics.jsonl when wandb is absent or offline")
    parser.add_argument("--wandb-project", default="trihouse-vision",
                        help="wandb project to log the run into")
    parser.add_argument("--min-fallen-per-eval-split", type=int, default=10)
    parser.add_argument("--min-mask-recall", type=float, default=0.90)
    parser.add_argument("--min-mask-map50", type=float, default=0.80)
    if include_run:
        parser.add_argument("--run-root", type=Path, default=Path("runs/lego_worker"))
        parser.add_argument("--name")
        parser.add_argument("--preflight-only", action="store_true")


def config_from_args(args: argparse.Namespace, **overrides) -> TrainingConfig:
    values = {
        "model": args.model, "data": args.data,
        "run_root": getattr(args, "run_root", Path("runs/lego_worker")),
        "name": getattr(args, "name", None),
        "augmentation": bool(args.augmentation), "augmentation_seed": args.augmentation_seed,
        "augmentation_holdout": tuple(sorted(set(getattr(args, "holdout", []) or ()))),
        "epochs": args.epochs,
        "imgsz": args.imgsz, "patience": args.patience, "batch": args.batch,
        "device": args.device, "workers": args.workers, "seed": args.seed,
        "posture_manifest": args.posture_manifest,
        "augmentation_source": getattr(args, "augmentation_source", None),
        "allow_posture_gap": args.allow_posture_gap,
        "preflight_only": getattr(args, "preflight_only", False),
        "min_fallen_per_eval_split": args.min_fallen_per_eval_split,
        "min_mask_recall": args.min_mask_recall, "min_mask_map50": args.min_mask_map50,
        "wandb": bool(getattr(args, "wandb", False)),
        "wandb_project": getattr(args, "wandb_project", "trihouse-vision"),
    }
    values.update(overrides)
    return TrainingConfig(**values)
