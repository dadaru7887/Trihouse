"""Single entrypoint for training the person/obstacle segmentation model.

    python -m vision_ai.models.perception.trainer.pipeline labels    --config <yaml>
    python -m vision_ai.models.perception.trainer.pipeline preflight --data <data.yaml> --output <dir>
    python -m vision_ai.models.perception.trainer.pipeline run       --data <data.yaml>   # one run
    python -m vision_ai.models.perception.trainer.pipeline train     --config <yaml>      # multi-seed
    python -m vision_ai.models.perception.trainer.pipeline evaluate  --run-dir <dir> --split val
    python -m vision_ai.models.perception.trainer.pipeline analyze   --experiment-dir <dir>

Flow: parse the stage, build a TrainingConfig from the arguments, hand it to
the code that owns that stage. This file routes; it trains nothing itself.

Every path is an argument, and defaults stay relative to the repo root, so
moving to another checkout or dataset needs no code change.

Running one seed is `trainer.seed_runner`, not a stage here: the multi-seed
experiment starts it as a separate process.
"""

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from vision_ai.models.perception.trainer.cli import add_training_arguments, config_from_args
from vision_ai.utils.config_loader import REPOSITORY_ROOT, load_experiment_config
from vision_ai.utils.run_config import TrainingConfig

DEFAULT_CONFIG = Path("vision_ai/models/perception/trainer/configs/config.yaml")


def _default_config() -> Path:
    return REPOSITORY_ROOT / DEFAULT_CONFIG


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Person/obstacle segmentation: dataloader -> trainer -> evaluation -> analysis"
    )
    stages = parser.add_subparsers(dest="stage", required=True)

    labels = stages.add_parser("labels", help="Analyse dataset label quality")
    labels.add_argument("--config", type=Path, default=_default_config())
    labels.add_argument("--data", type=Path, help="Overrides dataset.data_yaml from the config")
    labels.add_argument("--output", type=Path, default=Path("runs/label_analysis"))

    preflight = stages.add_parser("preflight", help="Check the dataset only, without training")
    add_training_arguments(preflight, include_run=False)
    preflight.add_argument("--output", type=Path, required=True, help="Run directory")

    run = stages.add_parser("run", help="One run: preflight -> train -> evaluate")
    add_training_arguments(run)

    train = stages.add_parser("train", help="Multi-seed train/validation/test")
    train.add_argument("--config", type=Path, default=_default_config())
    train.add_argument("--experiment-dir", type=Path)
    train.add_argument("--data", type=Path, help="Overrides dataset.data_yaml from the config")

    evaluate = stages.add_parser("evaluate", help="Score trained weights")
    evaluate.add_argument("--run-dir", type=Path, required=True)
    evaluate.add_argument("--weights", type=Path)
    evaluate.add_argument("--split", choices=("val", "test"), required=True)

    analyze = stages.add_parser("analyze", help="Analyse and plot a finished multi-seed experiment")
    analyze.add_argument("--experiment-dir", type=Path, required=True)
    analyze.add_argument("--output", type=Path)
    return parser


class _UnusedBackend:
    """Fail loudly if training is called under --preflight-only."""

    def train(self, *args, **kwargs):
        raise AssertionError("train must not be called in preflight-only mode")

    def evaluate(self, *args, **kwargs):
        raise AssertionError("evaluate must not be called in preflight-only mode")


def _labels(args: argparse.Namespace) -> int:
    from vision_ai.data_loader.perception.label_analysis import analyze_labels

    config = load_experiment_config(args.config, data_override=args.data)
    analyze_labels(config.training.data, args.output)
    print(args.output.resolve())
    return 0


def _preflight(args: argparse.Namespace) -> int:
    from vision_ai.data_loader.perception.audit import DatasetAuditError, audit_dataset

    from vision_ai.utils.device import resolve_device

    config = config_from_args(args, run_root=args.output.parent, name=args.output.name)
    # `evaluate` reads this config back and hands device to ultralytics, which
    # does not know the "auto" token, so resolve it before writing it down.
    config = dataclasses.replace(config, device=resolve_device(config.device).resolved)
    try:
        report = audit_dataset(
            config.data, args.output / "preflight", config.posture_manifest,
            config.allow_posture_gap, config.min_fallen_per_eval_split,
        )
    except DatasetAuditError as error:
        print(f"[PREFLIGHT FAILED] {error}", file=sys.stderr)
        return 2
    (args.output / "config").mkdir(parents=True, exist_ok=True)
    (args.output / "config/resolved.json").write_text(
        json.dumps(config.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"[PREFLIGHT OK] {report.fingerprint}")
    return 0


def _run(args: argparse.Namespace) -> int:
    from vision_ai.data_loader.perception.audit import DatasetAuditError
    from vision_ai.models.perception.trainer.orchestrator import PipelineError, run_pipeline

    config = config_from_args(args)
    try:
        if config.preflight_only:
            backend = _UnusedBackend()
        else:
            from vision_ai.models.perception.trainer.yoloe_trainer import YOLOEBackend

            backend = YOLOEBackend()
        run_dir = run_pipeline(config, backend)
    except (DatasetAuditError, PipelineError, ValueError, ImportError, RuntimeError) as error:
        print(f"[RUN FAILED] {error}", file=sys.stderr)
        return 2
    print(f"[RUN OK] {run_dir}")
    return 0


def _train(args: argparse.Namespace) -> int:
    from vision_ai.models.perception.trainer.experiment import MultiSeedExperiment

    selected = MultiSeedExperiment.from_config(
        args.config, args.experiment_dir, data_override=args.data
    ).run()
    print(f"[TRAIN OK] {selected}")
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    from vision_ai.models.perception.trainer.yoloe_trainer import YOLOEBackend

    config_path = args.run_dir / "config/resolved.json"
    if not config_path.is_file():
        print(f"no resolved config from preflight: {config_path}", file=sys.stderr)
        return 2
    config = TrainingConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
    weights = args.weights or args.run_dir / "train/weights/best.pt"
    metrics = YOLOEBackend().evaluate(weights, args.split, config, args.run_dir)
    output = args.run_dir / "evaluation" / f"{args.split}_metrics.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(f"[EVALUATE OK] split={args.split}, metrics={output}")
    return 0


def _analyze(args: argparse.Namespace) -> int:
    from vision_ai.visualization.report import analyze_experiment

    analyze_experiment(args.experiment_dir, args.output)
    print((args.output or args.experiment_dir / "analysis").resolve())
    return 0


STAGES = {
    "labels": _labels, "preflight": _preflight, "run": _run,
    "train": _train, "evaluate": _evaluate, "analyze": _analyze,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return STAGES[args.stage](args)


if __name__ == "__main__":
    raise SystemExit(main())
