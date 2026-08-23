"""Train the frozen TGRPO+SAC policy from executed recovery JSONL only."""

from __future__ import annotations

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=20)
    args = parser.parse_args(argv)
    # Keep data collection and physical inference importable on machines that
    # deliberately do not carry the CUDA training stack.
    from model.vlm_rl.training.offline_train import train

    dataset = args.dataset_dir / "recovery_transitions.jsonl"
    args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    train(dataset, args.checkpoint, args.epochs)


if __name__ == "__main__":
    main()
