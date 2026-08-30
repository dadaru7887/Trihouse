#!/usr/bin/env python3
"""Trihouse 사람·낙상 인식의 단일 진입점.

    # 학습 — dataloader 로 데이터를 의심하고, train/valid 로 정하고, test 는 한 번
    python main.py train --task segmentation    --data /path/to/data.yaml
    python main.py train --task fall-classifier --dataset /path/to/features.jsonl

    # 추론 — 로봇 카메라로 들어오는 영상을 실시간으로 처리해 주행에 넘긴다
    python main.py eval --source rtsp://<pc1>:8554/pinky/CAM-PK-01 \
                        --weights /models/best.pt --report-url http://<gateway>:8000

**두 갈래는 import 경계를 공유하지 않는다.** 여기의 import 는 전부 각 함수
안에 있고, `eval` 을 돌릴 때 학습 패키지는 한 줄도 적재되지 않는다. 로봇에
올라가는 프로세스가 ultralytics 학습 스택과 scikit-learn 을 끌고 들어가면
안 되기 때문이고, 그 보장은 주장이 아니라
`tests/test_main_entrypoint.py` 가 실제 프로세스의 `sys.modules` 로 잰다.

`eval` 이 하는 일은 **지표 계산이 아니라 실시간 추론**이다. 고정 데이터셋에
지표를 내는 쪽은 학습 파이프라인 안에 있다:

    python -m model.perception.segmentation.training.train evaluate \
        --run-dir runs/... --split test

들어온 영상이 주행에 닿는 경로는 이렇다.

    카메라 ──▶ eval(이 프로세스) ──▶ Gateway ──▶ 해당 로봇의 TCP 링크
                                                    │
                                                    ▼
                                        safety_supervisor_node
                                                    │
                                    pose_class 가 FALLEN/IMMOBILE/
                                    EMERGENCY_CANDIDATE 이면 감속이 아니라 정지
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Trihouse 사람·낙상 인식: train(학습) / eval(실시간 추론)",
    )
    modes = parser.add_subparsers(dest="mode", required=True)

    train = modes.add_parser("train", help="모델 학습 (dataloader → train/valid → test)")
    train.add_argument("--task", choices=("segmentation", "fall-classifier"), required=True)
    train.add_argument("--data", type=Path,
                       help="[segmentation] YOLO data.yaml. config 값을 덮어쓴다")
    train.add_argument("--config", type=Path,
                       help="[segmentation] 실험 config. 생략하면 저장소 기본값")
    train.add_argument("--dataset", type=Path,
                       help="[fall-classifier] 피처 JSONL (features/fallen/split)")
    train.add_argument("--out", type=Path,
                       help="[fall-classifier] 번들과 metrics.json 을 쓸 디렉터리")
    train.add_argument("--multi-seed", action="store_true",
                       help="[segmentation] seed 여러 개를 돌려 대표 모델까지 고른다")
    train.add_argument("--seed", type=int, default=42)
    train.add_argument("--min-recall", type=float, default=0.85,
                       help="[fall-classifier] 임계값 선택 시 만족해야 할 recall 바닥")
    train.add_argument("--epochs", type=int)
    train.add_argument("--device", default=None)
    train.add_argument("--run-root", type=Path,
                       help="[segmentation] run 디렉터리를 담을 곳")

    evaluate = modes.add_parser(
        "eval", help="카메라/영상 실시간 추론 — 결과를 주행 안전 gate 로 보낸다")
    evaluate.add_argument("--source", default="0",
                          help="RTSP URL, 영상 파일 경로, 또는 카메라 index")
    evaluate.add_argument("--weights", type=Path,
                          help="세그멘테이션 weight(.pt) 또는 selected_model.json")
    evaluate.add_argument("--config", type=Path,
                          help="realtime.yaml. 생략하면 저장소 기본값")
    evaluate.add_argument("--report-url",
                          help="Gateway person-detections endpoint. 생략하면 stdout 만")
    evaluate.add_argument("--camera-id",
                          help="RTSP URL 에 담겨 있지 않을 때만 필요")
    evaluate.add_argument("--ttl-ms", type=int, default=600)
    evaluate.add_argument("--headless", action="store_true", help="화면 표시 없이")
    evaluate.add_argument("--with-recovery", action="store_true",
                          help="VLM+RL 복구 제안까지 포함한 5080 운영 런타임으로 실행")
    evaluate.add_argument("--dry-run", action="store_true",
                          help="배선만 확인하고 카메라를 열지 않는다")
    return parser


def _train(args: argparse.Namespace) -> int:
    if args.task == "segmentation":
        from model.perception.segmentation.training.train import main as segmentation_main

        if args.multi_seed:
            argv = ["train"]
            if args.config:
                argv += ["--config", str(args.config)]
            if args.data:
                argv += ["--data", str(args.data)]
            return segmentation_main(argv)
        if not args.data:
            print("segmentation 학습에는 --data 가 필요합니다", file=sys.stderr)
            return 2
        argv = ["run", "--data", str(args.data), "--seed", str(args.seed)]
        if args.epochs is not None:
            argv += ["--epochs", str(args.epochs)]
        if args.device:
            argv += ["--device", args.device]
        if args.run_root:
            argv += ["--run-root", str(args.run_root)]
        return segmentation_main(argv)

    from model.worker.person.training.train import main as classifier_main

    if not args.dataset or not args.out:
        print("fall-classifier 학습에는 --dataset 과 --out 이 필요합니다", file=sys.stderr)
        return 2
    return classifier_main([
        "--dataset", str(args.dataset), "--out", str(args.out),
        "--seed", str(args.seed), "--min-recall", str(args.min_recall),
    ])


def _eval(args: argparse.Namespace) -> int:
    if args.with_recovery:
        if args.dry_run:
            print("eval --with-recovery: 5080 운영 런타임 (환경변수로 설정)")
            return 0
        from model.vlm_rl.inference.runtime import main as recovery_main

        return recovery_main([]) or 0

    if not args.weights:
        print("eval 에는 --weights 가 필요합니다", file=sys.stderr)
        return 2
    if args.dry_run:
        # 배선만 확인한다. 여기서 무거운 모듈을 적재하지 않는 것이 요점이다 —
        # 이 경로가 학습 패키지를 끌어오지 않는다는 것을 시험이 프로세스
        # 단위로 재고 있다.
        print(f"eval: source={args.source} weights={args.weights} "
              f"report_url={args.report_url or '(stdout only)'}")
        return 0

    from model.worker.person.worker import main as worker_main

    argv = ["--weights", str(args.weights), "--source", args.source,
            "--ttl-ms", str(args.ttl_ms)]
    if args.config:
        argv += ["--config", str(args.config)]
    if args.report_url:
        argv += ["--report-url", args.report_url]
    if args.camera_id:
        argv += ["--camera-id", args.camera_id]
    if args.headless:
        argv += ["--headless"]
    return worker_main(argv)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return _train(args) if args.mode == "train" else _eval(args)


if __name__ == "__main__":
    raise SystemExit(main())
