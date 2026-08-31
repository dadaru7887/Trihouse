#!/usr/bin/env python3
"""Training and validation entrypoint for the two Trihouse vision models.

    # perception -- person/obstacle segmentation (YOLOE)
    python -m vision_ai.main train --model perception --stage segmentation \
        --data data/pinky_camera/merged/data.yaml \
        --posture-manifest data/pinky_camera/merged/posture_manifest.csv

    # perception -- the same, over several seeds, picking a representative run
    python -m vision_ai.main train --model perception --stage segmentation \
        --data data/pinky_camera/merged/data.yaml --multi-seed

    # perception -- fall classifier (geometric features + logistic regression)
    python -m vision_ai.main train --model perception --stage fall \
        --dataset runs/fall/features.jsonl --out runs/fall

    # recovery -- TGRPO + SAC
    python -m vision_ai.main train --model recovery \
        --dataset dataset/vlm_rl/recovery_transitions.jsonl \
        --checkpoint runs/recovery/policy.pt

    # score trained weights against a fixed split
    python -m vision_ai.main eval --model perception --run-dir runs/... --split test

Flow: parse the arguments -> forward them to the trainer that owns the stage.
This file routes; it holds no training logic of its own.

**Training and validation only.** Live inference is a separate process with its
own entrypoint, because it must not pull in the training stack:

    python -m vision_ai.robot.main --source rtsp://... --weights /models/best.pt

Which weights each model produces, and where the robot reads them:

    perception  best.pt (YOLOE) + fallen_classifier.joblib  -> robot/perception/
    recovery    policy.pt (TGRPO+SAC) + ensemble.pt         -> robot/recovery/

Every import sits inside a branch function. `tests/test_main_entrypoint.py`
starts a real process and reads sys.modules to prove the robot side stays clear
of the training stack.
"""

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    """Define the command line.

    Arguments are grouped by the stage that uses them; the [stage] prefix in
    each help string says which. An argument for another stage is ignored, so
    the branch functions check for the ones they need and fail loudly.
    """
    parser = argparse.ArgumentParser(
        prog="vision_ai.main",
        description="Trihouse vision AI: train and validate the perception and recovery models",
    )
    modes = parser.add_subparsers(dest="mode", required=True)

    # ------------------------------------------------------------- train --
    train = modes.add_parser(
        "train", help="Train a model (data_loader -> train/valid -> test)")

    # Which model, and which stage of it.
    train.add_argument("--model", choices=("perception", "recovery"), required=True,
                       help="perception = segmentation + fall classifier, "
                            "recovery = TGRPO/SAC recovery policy")
    train.add_argument("--stage", choices=("segmentation", "fall"), default="segmentation",
                       help="[perception] which stage to train")

    # Inputs.
    train.add_argument("--data", type=Path,
                       help="[segmentation] YOLO data.yaml")
    train.add_argument("--posture-manifest", type=Path,
                       help="[segmentation] per-frame fallen/standing CSV. Preflight counts "
                            "the fallen samples in each eval split from this")
    train.add_argument("--config", type=Path,
                       help="[segmentation] experiment config, for --multi-seed")
    train.add_argument("--dataset", type=Path,
                       help="[fall] feature JSONL, [recovery] transition JSONL")

    # Outputs.
    train.add_argument("--run-root", type=Path,
                       help="[segmentation] parent directory for the run")
    train.add_argument("--out", type=Path,
                       help="[fall] output directory")
    train.add_argument("--checkpoint", type=Path,
                       help="[recovery] policy checkpoint to write")

    # How to train.
    train.add_argument("--epochs", type=int,
                       help="[segmentation, recovery] overrides the config default")
    train.add_argument("--device",
                       help="[segmentation] auto (cuda > mps > cpu), cpu, mps, "
                            "gpu/cuda or a GPU index")
    train.add_argument("--seed", type=int, default=42,
                       help="Seeds torch, numpy and random. Augmentation draws from a "
                            "separate stream so this stays reproducible")
    train.add_argument("--multi-seed", action="store_true",
                       help="[segmentation] train several seeds and pick a representative run")
    train.add_argument("--min-recall", type=float, default=0.85,
                       help="[fall] recall floor the decision threshold must meet")
    train.add_argument("--allow-posture-gap", action="store_true",
                       help="[segmentation] train detection only, accepting too few "
                            "fallen samples to validate the fall stage")

    # -------------------------------------------------------------- eval --
    evaluate = modes.add_parser(
        "eval", help="Score trained weights against a fixed split")
    evaluate.add_argument("--model", choices=("perception",), default="perception")
    evaluate.add_argument("--run-dir", type=Path, required=True,
                          help="Run directory holding config/resolved.json")
    evaluate.add_argument("--weights", type=Path,
                          help="Defaults to <run-dir>/train/weights/best.pt")
    evaluate.add_argument("--split", choices=("val", "test"), required=True,
                          help="test is opened once, at the end")
    return parser


def _train_perception(args: argparse.Namespace) -> int:
    """Route to the segmentation pipeline or the fall classifier trainer."""
    if args.stage == "fall":
        from vision_ai.models.perception.trainer.fall_trainer import main as fall_main

        if not args.dataset or not args.out:
            print("fall training needs --dataset and --out", file=sys.stderr)
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
        print("segmentation training needs --data", file=sys.stderr)
        return 2
    argv = ["run", "--data", str(args.data), "--seed", str(args.seed)]
    # Only forward what was given; the pipeline owns every default.
    if args.posture_manifest:
        argv += ["--posture-manifest", str(args.posture_manifest)]
    if args.allow_posture_gap:
        argv += ["--allow-posture-gap"]
    if args.epochs is not None:
        argv += ["--epochs", str(args.epochs)]
    if args.device:
        argv += ["--device", args.device]
    if args.run_root:
        argv += ["--run-root", str(args.run_root)]
    return pipeline_main(argv)


def _train_recovery(args: argparse.Namespace) -> int:
    """Route to the offline TGRPO/SAC trainer."""
    if not args.dataset or not args.checkpoint:
        print("recovery training needs --dataset and --checkpoint", file=sys.stderr)
        return 2
    from vision_ai.models.recovery.trainer.offline_train import main as recovery_main

    argv = [str(args.dataset), "--checkpoint", str(args.checkpoint)]
    if args.epochs is not None:
        argv += ["--epochs", str(args.epochs)]
    # offline_train reads sys.argv rather than taking a list, so swap it and
    # put it back; leaving it changed would break anything called afterwards.
    saved = sys.argv
    try:
        sys.argv = ["offline_train", *argv]
        recovery_main()
    finally:
        sys.argv = saved
    return 0


def _eval(args: argparse.Namespace) -> int:
    """Route to the pipeline's evaluate stage."""
    from vision_ai.models.perception.trainer.pipeline import main as pipeline_main

    argv = ["evaluate", "--run-dir", str(args.run_dir), "--split", args.split]
    if args.weights:
        argv += ["--weights", str(args.weights)]
    return pipeline_main(argv)


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and hand off to the matching trainer."""
    args = build_parser().parse_args(argv)
    if args.mode == "eval":
        return _eval(args)
    return _train_perception(args) if args.model == "perception" else _train_recovery(args)


if __name__ == "__main__":
    raise SystemExit(main())
