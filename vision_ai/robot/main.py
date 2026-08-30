#!/usr/bin/env python3
"""로봇에 올라가는 프로세스. 카메라 영상을 실시간으로 읽어 주행 판단으로 보낸다.

    # 인지만 — 사람/장애물 검출 + 낙상 상태머신 → Gateway → 로봇 안전 gate
    python -m vision_ai.robot.main --source rtsp://<pc1>:8554/pinky/CAM-PK-01 \
        --weights /models/best.pt --report-url http://<gateway>:8000

    # 인지 + 복구 — 위에 VLM+RL 복구 제안까지 (5080 운영 런타임, 환경변수로 설정)
    python -m vision_ai.robot.main --with-recovery

**이 프로세스는 학습 코드를 적재하지 않는다.** 두 모델이 만든 가중치 파일만
읽는다.

    ① 인지   best.pt (YOLOE) + fallen_classifier.joblib
    ② 복구   policy.pt (TGRPO+SAC) + high_level_distilled_ensemble.pt

학습·검증은 `vision_ai.main` 이 맡고, 그쪽 import 는 여기 한 줄도 들어오지
않는다. 코드 상 경계는 `vision_ai/tests/recovery/test_inference_boundary.py`
와 `tests/test_main_entrypoint.py` 가 지키고, 배포 이미지에 실제로 안 들어간다는
것은 `docker/ai/Dockerfile.inference` 의 COPY 목록이 정한다.

영상 한 장이 주행에 닿기까지:

    카메라 ─▶ 이 프로세스 ─▶ Gateway ─▶ 해당 로봇 TCP 링크
                                            │
                                  safety_supervisor_node
                                            │
                    pose_class 가 FALLEN/IMMOBILE/EMERGENCY_CANDIDATE 이면
                    감속이 아니라 정지
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vision_ai.robot.main",
        description="로봇 실시간 추론: 카메라 → 인지(+복구) → 주행 안전 gate",
    )
    parser.add_argument("--source", default="0",
                        help="RTSP URL, 영상 파일 경로, 또는 카메라 index")
    parser.add_argument("--weights", type=Path,
                        help="세그멘테이션 weight(.pt) 또는 selected_model.json")
    parser.add_argument("--config", type=Path, help="realtime.yaml")
    parser.add_argument("--report-url", help="Gateway person-detections endpoint")
    parser.add_argument("--camera-id", help="RTSP URL 에 담겨 있지 않을 때만 필요")
    parser.add_argument("--ttl-ms", type=int, default=600)
    parser.add_argument("--headless", action="store_true", help="화면 표시 없이")
    parser.add_argument("--with-recovery", action="store_true",
                        help="VLM+RL 복구 제안까지 포함한 5080 운영 런타임")
    parser.add_argument("--dry-run", action="store_true",
                        help="배선만 확인하고 카메라를 열지 않는다")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.with_recovery:
        if args.dry_run:
            print("robot: 복구 포함 런타임 (나머지 설정은 환경변수)")
            return 0
        from vision_ai.robot.recovery.runtime import main as recovery_main

        return recovery_main([]) or 0

    if not args.weights:
        print("--weights 가 필요합니다", file=sys.stderr)
        return 2
    if args.dry_run:
        # 배선만 확인한다. 여기서 무거운 모듈을 적재하지 않는 것이 요점이다 —
        # 이 경로가 학습 패키지를 끌어오지 않는다는 것을 시험이 프로세스
        # 단위로 재고 있다.
        print(f"robot: source={args.source} weights={args.weights} "
              f"report_url={args.report_url or '(stdout only)'}")
        return 0

    from vision_ai.robot.perception.worker import main as perception_main

    argv_worker = ["--weights", str(args.weights), "--source", args.source,
                   "--ttl-ms", str(args.ttl_ms)]
    if args.config:
        argv_worker += ["--config", str(args.config)]
    if args.report_url:
        argv_worker += ["--report-url", args.report_url]
    if args.camera_id:
        argv_worker += ["--camera-id", args.camera_id]
    if args.headless:
        argv_worker += ["--headless"]
    return perception_main(argv_worker)


if __name__ == "__main__":
    raise SystemExit(main())
