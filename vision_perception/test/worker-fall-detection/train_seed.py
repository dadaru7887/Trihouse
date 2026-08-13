import argparse
import dataclasses
from pathlib import Path

from pipeline.config_loader import config_for_seed, load_experiment_config
from pipeline.orchestrator import run_pipeline
from trainer.yoloe_trainer import YOLOEBackend


def main() -> None:
    parser = argparse.ArgumentParser(description="하나의 seed로 YOLOE 학습/검증/test 실행")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--experiment-dir", type=Path, required=True)
    args = parser.parse_args()
    experiment = load_experiment_config(args.config)
    config = config_for_seed(experiment, args.seed)
    config = dataclasses.replace(config, run_root=args.experiment_dir.resolve())
    run_pipeline(config, YOLOEBackend())


if __name__ == "__main__":
    main()
