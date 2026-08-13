#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from pipeline.run_config import TrainingConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="학습된 LEGO YOLOE weight 평가")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--split", choices=("val", "test"), required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.run_dir / "config/resolved.json"
    if not config_path.is_file():
        raise SystemExit(f"preflight resolved config가 없습니다: {config_path}")
    config = TrainingConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
    weights = args.weights or args.run_dir / "train/weights/best.pt"
    from trainer.yoloe_trainer import YOLOEBackend

    metrics = YOLOEBackend().evaluate(weights, args.split, config, args.run_dir)
    output = args.run_dir / "evaluation" / f"{args.split}_metrics.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(f"[EVALUATE 완료] split={args.split}, metrics={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
