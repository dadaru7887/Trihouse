#!/usr/bin/env python3
import argparse
import sys

from pipeline.cli import add_training_arguments, config_from_args
from pipeline.dataset_audit import DatasetAuditError
from pipeline.orchestrator import PipelineError, run_pipeline


class _UnusedBackend:
    def train(self, *args, **kwargs):
        raise AssertionError("preflight-only에서 train이 호출되면 안 됩니다")
    def evaluate(self, *args, **kwargs):
        raise AssertionError("preflight-only에서 evaluate가 호출되면 안 됩니다")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LEGO worker YOLOE 학습·평가 전체 파이프라인")
    add_training_arguments(parser)
    return parser.parse_args()


def main() -> int:
    config = config_from_args(parse_args())
    try:
        if config.preflight_only:
            backend = _UnusedBackend()
        else:
            from pipeline.yoloe_backend import YOLOEBackend
            backend = YOLOEBackend()
        run_dir = run_pipeline(config, backend)
    except (DatasetAuditError, PipelineError, ValueError, ImportError, RuntimeError) as error:
        print(f"[PIPELINE 실패] {error}", file=sys.stderr)
        return 2
    print(f"[PIPELINE 완료] {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
