import argparse
from pathlib import Path

from pipeline.config_loader import load_experiment_config


PROJECT_DIR = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LEGO YOLOE: dataloader → trainer → evaluation → analysis")
    subparsers = parser.add_subparsers(dest="stage", required=True)
    labels = subparsers.add_parser("labels", help="dataset label 품질 분석")
    labels.add_argument("--config", type=Path, default=PROJECT_DIR / "configs/config.yaml")
    labels.add_argument("--output", type=Path, default=Path("runs/lego_label_analysis"))
    train = subparsers.add_parser("train", help="multi-seed 학습/validation/test")
    train.add_argument("--config", type=Path, default=PROJECT_DIR / "configs/config.yaml")
    train.add_argument("--experiment-dir", type=Path)
    analysis = subparsers.add_parser("analyze", help="완료된 multi-seed 결과 분석/시각화")
    analysis.add_argument("--experiment-dir", type=Path, required=True)
    analysis.add_argument("--output", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.stage == "labels":
        from dataloader.label_analysis import analyze_labels
        config = load_experiment_config(args.config)
        analyze_labels(config.training.data, args.output)
        print(args.output.resolve())
    elif args.stage == "train":
        from trainer.experiment import MultiSeedExperiment
        MultiSeedExperiment.from_config(args.config, args.experiment_dir).run()
    else:
        from analysis.report import analyze_experiment
        analyze_experiment(args.experiment_dir, args.output)
        print((args.output or args.experiment_dir / "analysis").resolve())


if __name__ == "__main__":
    main()
