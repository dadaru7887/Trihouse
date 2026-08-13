import argparse
from pathlib import Path

from trainer.experiment import MultiSeedExperiment


def main() -> None:
    parser = argparse.ArgumentParser(description="격리 subprocess 기반 multi-seed YOLOE 학습")
    parser.add_argument("--config", type=Path, default=Path(__file__).parent / "configs/config.yaml")
    parser.add_argument("--experiment-dir", type=Path)
    args = parser.parse_args()
    selected_model = MultiSeedExperiment.from_config(args.config, args.experiment_dir).run()
    print(selected_model)


if __name__ == "__main__":
    main()
