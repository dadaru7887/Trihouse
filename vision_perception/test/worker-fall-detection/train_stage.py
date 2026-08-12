#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline.run_config import TrainingConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="preflight 완료 run의 YOLOE 학습 단계 실행")
    parser.add_argument("--run-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.run_dir / "config/resolved.json"
    if not config_path.is_file():
        raise SystemExit(f"preflight resolved config가 없습니다: {config_path}")
    config = TrainingConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
    from pipeline.yoloe_backend import YOLOEBackend

    weights = YOLOEBackend().train(config, args.run_dir)
    result = args.run_dir / "train_stage.json"
    result.write_text(json.dumps({"weights": str(weights.resolve())}, indent=2) + "\n", encoding="utf-8")
    print(f"[TRAIN 완료] {weights}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
