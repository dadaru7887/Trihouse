#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline.cli import add_training_arguments, config_from_args
from pipeline.dataset_audit import DatasetAuditError, audit_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LEGO person dataset 학습 전 검사")
    add_training_arguments(parser, include_run=False)
    parser.add_argument("--output", type=Path, required=True, help="수동 실행 run 디렉터리")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = config_from_args(args, run_root=args.output.parent, name=args.output.name)
    try:
        report = audit_dataset(
            config.data, args.output / "preflight", config.posture_manifest,
            config.allow_posture_gap, config.min_fallen_per_eval_split,
        )
    except DatasetAuditError as error:
        print(f"[PREFLIGHT 실패] {error}", file=sys.stderr)
        return 2
    path = args.output / "config/resolved.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[PREFLIGHT 완료] {args.output.resolve()}")
    print(f"dataset={report.dataset_status}, posture={report.posture_status}, fingerprint={report.fingerprint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
