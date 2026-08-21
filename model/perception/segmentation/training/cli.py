import argparse
from pathlib import Path

from .run_config import TrainingConfig


def add_training_arguments(parser: argparse.ArgumentParser, *, include_run: bool = True) -> None:
    parser.add_argument("--data", type=Path, required=True, help="YOLO segmentation data.yaml")
    parser.add_argument("--model", default="26s", help="YOLOE 축약명(예: 26s) 또는 .pt 경로")
    parser.add_argument("--augmentation", choices=("yes", "no"), default="yes")
    parser.add_argument("--augmentation-seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--batch", type=int, default=-1)
    parser.add_argument("--device", default="auto", help="auto, cpu, gpu/cuda 또는 GPU index")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--posture-manifest", type=Path)
    parser.add_argument(
        "--augmentation-source",
        type=Path,
        help="S1~S5 증강 recipe 모듈 경로. 생략하면 저장소의 "
             "model/perception/segmentation/train.py 를 쓴다",
    )
    parser.add_argument("--allow-posture-gap", action="store_true")
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
        "augmentation": args.augmentation == "yes", "augmentation_seed": args.augmentation_seed,
        "epochs": args.epochs,
        "imgsz": args.imgsz, "patience": args.patience, "batch": args.batch,
        "device": args.device, "workers": args.workers, "seed": args.seed,
        "posture_manifest": args.posture_manifest,
        "augmentation_source": getattr(args, "augmentation_source", None),
        "allow_posture_gap": args.allow_posture_gap,
        "preflight_only": getattr(args, "preflight_only", False),
        "min_fallen_per_eval_split": args.min_fallen_per_eval_split,
        "min_mask_recall": args.min_mask_recall, "min_mask_map50": args.min_mask_map50,
    }
    values.update(overrides)
    return TrainingConfig(**values)
