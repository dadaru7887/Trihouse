#!/usr/bin/env python3
"""Trihouse vision AI 두 모델의 학습·검증 진입점.

    # ① 인지 모델 — 사람/장애물 segmentation
    python -m vision_ai.main train --model perception --stage segmentation \
        --data /path/to/data.yaml
    python -m vision_ai.main train --model perception --stage segmentation \
        --data /path/to/data.yaml --multi-seed          # 대표 모델 선정까지

    # ① 인지 모델 — 낙상 분류기(기하 피처 + logreg)
    python -m vision_ai.main train --model perception --stage fall \
        --dataset /path/to/features.jsonl --out runs/fall

    # ② 복구 모델 — TGRPO + SAC
    python -m vision_ai.main train --model recovery \
        --dataset dataset/vlm_rl/recovery_transitions.jsonl \
        --checkpoint runs/recovery/policy.pt

    # 검증 — 학습된 가중치를 고정 데이터셋에 재기
    python -m vision_ai.main eval --model perception --run-dir runs/... --split test

**여기는 학습·검증만 한다.** 실시간 추론은 로봇 프로세스가 맡고 진입점이 따로다:

    python -m vision_ai.robot.main --source rtsp://... --weights /models/best.pt

두 모델이 내는 가중치와, 로봇이 그것을 읽는 자리는 이렇게 갈린다.

    ① 인지   best.pt (YOLOE) + fallen_classifier.joblib  ─▶ robot/perception/
    ② 복구   policy.pt (TGRPO+SAC) + ensemble.pt (distill) ─▶ robot/recovery/

import 는 전부 각 갈래 함수 안에 있다. 로봇 프로세스가 학습 스택을 끌고 들어가지
않는다는 보장은 `tests/test_main_entrypoint.py` 가 실제 프로세스의 `sys.modules`
로 잰다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vision_ai.main",
        description="Trihouse vision AI: 인지 모델 / 복구 모델 학습·검증",
    )
    modes = parser.add_subparsers(dest="mode", required=True)

    train = modes.add_parser("train", help="학습 (data_loader → train/valid → test)")
    train.add_argument("--model", choices=("perception", "recovery"), required=True)
    train.add_argument("--stage", choices=("segmentation", "fall"), default="segmentation",
                       help="[perception] 어느 단계를 학습할지")
    train.add_argument("--data", type=Path, help="[segmentation] YOLO data.yaml")
    train.add_argument("--config", type=Path, help="[segmentation] 실험 config")
    train.add_argument("--multi-seed", action="store_true",
                       help="[segmentation] seed 여러 개 → 대표 모델 선정")
    train.add_argument("--dataset", type=Path,
                       help="[fall] 피처 JSONL · [recovery] 전이 JSONL")
    train.add_argument("--out", type=Path, help="[fall] 산출물 디렉터리")
    train.add_argument("--checkpoint", type=Path, help="[recovery] 저장할 정책 체크포인트")
    train.add_argument("--run-root", type=Path, help="[segmentation] run 디렉터리 상위")
    train.add_argument("--epochs", type=int)
    train.add_argument("--device")
    train.add_argument("--seed", type=int, default=42)
    train.add_argument("--min-recall", type=float, default=0.85, help="[fall] recall 바닥")

    evaluate = modes.add_parser("eval", help="검증 — 고정 데이터셋에 지표를 낸다")
    evaluate.add_argument("--model", choices=("perception",), default="perception")
    evaluate.add_argument("--run-dir", type=Path, required=True)
    evaluate.add_argument("--weights", type=Path)
    evaluate.add_argument("--split", choices=("val", "test"), required=True)
    return parser


def _train_perception(args: argparse.Namespace) -> int:
    if args.stage == "fall":
        from vision_ai.models.perception.trainer.fall_trainer import main as fall_main

        if not args.dataset or not args.out:
            print("fall 학습에는 --dataset 과 --out 이 필요합니다", file=sys.stderr)
            return 2
        return fall_main([
            "--dataset", str(args.dataset), "--out", str(args.out),
            "--seed", str(args.seed), "--min-recall", str(args.min_recall),
        ])

    from vision_ai.models.perception.trainer.pipeline import main as pipeline_main

    if args.multi_seed:
        argv = ["train"]
        if args.config:
            argv += ["--config", str(args.config)]
        if args.data:
            argv += ["--data", str(args.data)]
        return pipeline_main(argv)
    if not args.data:
        print("segmentation 학습에는 --data 가 필요합니다", file=sys.stderr)
        return 2
    argv = ["run", "--data", str(args.data), "--seed", str(args.seed)]
    if args.epochs is not None:
        argv += ["--epochs", str(args.epochs)]
    if args.device:
        argv += ["--device", args.device]
    if args.run_root:
        argv += ["--run-root", str(args.run_root)]
    return pipeline_main(argv)


def _train_recovery(args: argparse.Namespace) -> int:
    if not args.dataset or not args.checkpoint:
        print("recovery 학습에는 --dataset 과 --checkpoint 가 필요합니다", file=sys.stderr)
        return 2
    from vision_ai.models.recovery.trainer.offline_train import main as recovery_main

    argv = [str(args.dataset), "--checkpoint", str(args.checkpoint)]
    if args.epochs is not None:
        argv += ["--epochs", str(args.epochs)]
    saved = sys.argv
    try:
        sys.argv = ["offline_train", *argv]
        recovery_main()
    finally:
        sys.argv = saved
    return 0


def _eval(args: argparse.Namespace) -> int:
    from vision_ai.models.perception.trainer.pipeline import main as pipeline_main

    argv = ["evaluate", "--run-dir", str(args.run_dir), "--split", args.split]
    if args.weights:
        argv += ["--weights", str(args.weights)]
    return pipeline_main(argv)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "eval":
        return _eval(args)
    return _train_perception(args) if args.model == "perception" else _train_recovery(args)


if __name__ == "__main__":
    raise SystemExit(main())
