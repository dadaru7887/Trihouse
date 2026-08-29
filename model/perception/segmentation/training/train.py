"""사람/장애물 검출 모델의 학습 단일 진입점.

옮기기 전에는 진입점이 일곱 개였다 — `main.py`, `run_pipeline.py`, `preflight.py`,
`train_stage.py`, `evaluate_stage.py`, `train_seed.py`, `train_multi_seed.py`.
같은 학습을 시작하는 길이 세 갈래로 갈려 있어 어느 것이 정본인지 알 수 없었다.
여기서 하나로 모은다.

    python -m model.perception.segmentation.training.train labels    --config <yaml>
    python -m model.perception.segmentation.training.train preflight --data <data.yaml> --output <dir>
    python -m model.perception.segmentation.training.train run       --data <data.yaml>       # 단일 run
    python -m model.perception.segmentation.training.train train     --config <yaml>          # multi-seed
    python -m model.perception.segmentation.training.train evaluate  --run-dir <dir> --split val
    python -m model.perception.segmentation.training.train analyze   --experiment-dir <dir>

**경로는 전부 인자다.** 기본값도 저장소 루트 기준 상대 경로로만 두고 절대 경로를
코드에 넣지 않는다 — 다른 체크아웃이나 다른 데이터셋으로 옮길 때 코드를 고치지
않아야 한다.

seed 하나를 돌리는 것은 `model.perception.segmentation.training.seed_runner` 다. multi-seed 실험이
프로세스로 띄우므로 여기 subcommand 로 두지 않는다.
"""

import argparse
import json
import sys
from pathlib import Path

from model.perception.segmentation.training.cli import add_training_arguments, config_from_args
from model.perception.segmentation.training.config_loader import REPOSITORY_ROOT, load_experiment_config
from model.perception.segmentation.training.run_config import TrainingConfig

DEFAULT_CONFIG = Path("model/perception/segmentation/training/configs/config.yaml")


def _default_config() -> Path:
    return REPOSITORY_ROOT / DEFAULT_CONFIG


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="사람/장애물 검출 학습: dataloader → trainer → evaluation → analysis"
    )
    stages = parser.add_subparsers(dest="stage", required=True)

    labels = stages.add_parser("labels", help="dataset label 품질 분석")
    labels.add_argument("--config", type=Path, default=_default_config())
    labels.add_argument("--data", type=Path, help="config 의 dataset.data_yaml 을 덮어쓴다")
    labels.add_argument("--output", type=Path, default=Path("runs/label_analysis"))

    preflight = stages.add_parser("preflight", help="학습 전 dataset 검사만")
    add_training_arguments(preflight, include_run=False)
    preflight.add_argument("--output", type=Path, required=True, help="run 디렉터리")

    run = stages.add_parser("run", help="단일 run: preflight → 학습 → 평가")
    add_training_arguments(run)

    train = stages.add_parser("train", help="multi-seed 학습/validation/test")
    train.add_argument("--config", type=Path, default=_default_config())
    train.add_argument("--experiment-dir", type=Path)
    train.add_argument("--data", type=Path, help="config 의 dataset.data_yaml 을 덮어쓴다")

    evaluate = stages.add_parser("evaluate", help="학습된 weight 평가")
    evaluate.add_argument("--run-dir", type=Path, required=True)
    evaluate.add_argument("--weights", type=Path)
    evaluate.add_argument("--split", choices=("val", "test"), required=True)

    analyze = stages.add_parser("analyze", help="완료된 multi-seed 결과 분석/시각화")
    analyze.add_argument("--experiment-dir", type=Path, required=True)
    analyze.add_argument("--output", type=Path)
    return parser


class _UnusedBackend:
    """`--preflight-only` 에서 학습이 호출되면 조용히 넘어가지 않고 터진다."""

    def train(self, *args, **kwargs):
        raise AssertionError("preflight-only 에서 train 이 호출되면 안 됩니다")

    def evaluate(self, *args, **kwargs):
        raise AssertionError("preflight-only 에서 evaluate 가 호출되면 안 됩니다")


def _labels(args: argparse.Namespace) -> int:
    from model.perception.segmentation.training.dataloader.label_analysis import analyze_labels

    config = load_experiment_config(args.config, data_override=args.data)
    analyze_labels(config.training.data, args.output)
    print(args.output.resolve())
    return 0


def _preflight(args: argparse.Namespace) -> int:
    from model.perception.segmentation.training.dataloader.audit import DatasetAuditError, audit_dataset

    config = config_from_args(args, run_root=args.output.parent, name=args.output.name)
    try:
        report = audit_dataset(
            config.data, args.output / "preflight", config.posture_manifest,
            config.allow_posture_gap, config.min_fallen_per_eval_split,
        )
    except DatasetAuditError as error:
        print(f"[PREFLIGHT 실패] {error}", file=sys.stderr)
        return 2
    (args.output / "config").mkdir(parents=True, exist_ok=True)
    (args.output / "config/resolved.json").write_text(
        json.dumps(config.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"[PREFLIGHT 완료] {report.fingerprint}")
    return 0


def _run(args: argparse.Namespace) -> int:
    from model.perception.segmentation.training.dataloader.audit import DatasetAuditError
    from model.perception.segmentation.training.orchestrator import PipelineError, run_pipeline

    config = config_from_args(args)
    try:
        if config.preflight_only:
            backend = _UnusedBackend()
        else:
            from model.perception.segmentation.training.trainer.yoloe_trainer import YOLOEBackend

            backend = YOLOEBackend()
        run_dir = run_pipeline(config, backend)
    except (DatasetAuditError, PipelineError, ValueError, ImportError, RuntimeError) as error:
        print(f"[RUN 실패] {error}", file=sys.stderr)
        return 2
    print(f"[RUN 완료] {run_dir}")
    return 0


def _train(args: argparse.Namespace) -> int:
    from model.perception.segmentation.training.trainer.experiment import MultiSeedExperiment

    selected = MultiSeedExperiment.from_config(
        args.config, args.experiment_dir, data_override=args.data
    ).run()
    print(f"[TRAIN 완료] {selected}")
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    from model.perception.segmentation.training.trainer.yoloe_trainer import YOLOEBackend

    config_path = args.run_dir / "config/resolved.json"
    if not config_path.is_file():
        print(f"preflight resolved config 가 없습니다: {config_path}", file=sys.stderr)
        return 2
    config = TrainingConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
    weights = args.weights or args.run_dir / "train/weights/best.pt"
    metrics = YOLOEBackend().evaluate(weights, args.split, config, args.run_dir)
    output = args.run_dir / "evaluation" / f"{args.split}_metrics.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(f"[EVALUATE 완료] split={args.split}, metrics={output}")
    return 0


def _analyze(args: argparse.Namespace) -> int:
    from model.perception.segmentation.training.analysis.report import analyze_experiment

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
