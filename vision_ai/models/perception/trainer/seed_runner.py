"""Run train, validation and test for one seed. The multi-seed experiment starts it.

    python -m vision_ai.models.perception.trainer.seed_runner --config <yaml> --seed 42

**Invoked as a module, not a script path.** A path would make the experiment
depend on knowing where its own source lives, and that breaks silently the
moment a folder moves; the module name survives a change of layout.

Each seed gets a fresh process because reproducibility needs one: PYTHONHASHSEED
cannot be changed after the interpreter starts, and CUDA/cuDNN keep global
state, so seeds run in one process leak into each other.
"""

import argparse
import dataclasses
from pathlib import Path

from vision_ai.utils.config_loader import config_for_seed, load_experiment_config
from vision_ai.models.perception.trainer.orchestrator import run_pipeline
from vision_ai.models.perception.trainer.yoloe_trainer import YOLOEBackend


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run YOLOE train/validation/test for one seed")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--experiment-dir", type=Path, required=True)
    # When the parent experiment overrode the config with --data, that value
    # has to reach here; otherwise this child quietly trains on the config path.
    parser.add_argument("--data", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    experiment = load_experiment_config(args.config, data_override=args.data)
    config = config_for_seed(experiment, args.seed)
    config = dataclasses.replace(config, run_root=args.experiment_dir.resolve())
    run_pipeline(config, YOLOEBackend())


if __name__ == "__main__":
    main()
