"""사람 검출 + 낙상 감지 추론 진입점.

    python -m vision_system.person_worker.worker \
      --weights runs/.../selected_model.json --source rtsp://... --headless

세 단계를 잇기만 한다. 판단은 각 단계 안에 있다.

    frame ─▶ Detector          1단계. 사람/장애물 검출          (yolo_inference_server)
              └─▶ PostureEstimator  2단계. 자세·움직임 **측정**  (posture.py)
                    └─▶ FallMonitor  시간축 상태 전이            (fall_monitor.py)

한 번의 추론에서 두 갈래가 나온다.

    Detection.confidence + box  ──▶  사람 위치·신뢰도  (로봇 안전 gate 로)
    FallState                   ──▶  낙상 이벤트      (관제로)

전에는 두 번째 갈래만 쓰고 첫 번째를 버렸다. 로봇의 `safety_supervisor` 가 사람을
못 보던 이유가 그것이다 — 라이다는 사람과 벽을 구분하지 못한다.

## 이 코드가 하지 않는 것

ROS 발행을 하지 않는다. `PersonDetection` 을 내는 노드는 이 결과를 받아 얇게
붙는다. 여기서 rclpy 를 끌어오면 GPU 서버에서 ROS 없이 영상만 돌려 보는 일이
불가능해진다.
"""

import argparse
import json
import math
import time
from pathlib import Path

import yaml

from vision_system.person_worker.fall_monitor import FallMonitor, MonitorConfig
from vision_system.person_worker.posture import PostureConfig, PostureEstimator
from vision_system.person_worker.reporting import ReportPolicy, ReportThrottle
from vision_system.yolo_inference_server.detector import Detector, DetectorConfig

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "configs/realtime.yaml"

# 낙상 확정 후보를 관제에 올릴 때 쓰는 이름. 사람이 재확인하는 절차의 입구다 —
# 이 이벤트가 곧 "넘어졌다" 는 결론은 아니다.
FALL_EVENT = "WORKER_FALL_CONFIRMATION_REQUEST"


def parse_source(value: str):
    """숫자면 카메라 index, 아니면 파일 경로나 RTSP URL."""
    return int(value) if value.isdigit() else value


def load_settings(path: Path) -> tuple[DetectorConfig, PostureConfig, MonitorConfig]:
    """`realtime.yaml` 하나에서 세 단계의 설정을 갈라 낸다.

    `monitor` 절이 자세 임계값과 시간축 임계값을 함께 담고 있어 둘로 나눈다.
    한 파일에 두는 이유는 현장에서 튜닝할 때 같이 움직이는 값들이기 때문이다.
    """
    settings = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    inference = settings.get("inference", {})
    monitor = settings.get("monitor", {})
    detector = DetectorConfig(**inference)
    posture = PostureConfig(
        fall_aspect_ratio=float(monitor.get("fall_aspect_ratio", 0.9)),
        motion_threshold=float(monitor.get("motion_threshold", 0.015)),
    )
    return detector, posture, MonitorConfig(**monitor)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="사람 검출 + 낙상 감지 추론")
    parser.add_argument("--weights", type=Path, required=True, help="best.pt 또는 selected_model.json")
    parser.add_argument("--source", default="0", help="카메라 번호, 영상 파일 또는 RTSP URL")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--headless", action="store_true", help="창을 띄우지 않는다")
    parser.add_argument(
        "--camera-id",
        help=(
            "관측에 실을 카메라 ID. RTSP source 면 URL 의 마지막 segment 에서 "
            "저절로 나오므로 줄 필요가 없다"
        ),
    )
    parser.add_argument(
        "--report-url",
        help="관제(4060)의 사람 관측 수신 주소. 생략하면 표준출력에만 찍는다",
    )
    parser.add_argument(
        "--ttl-ms",
        type=int,
        default=ReportPolicy().ttl_ms,
        help="관측 수명(ms). 이 절반 주기로 갱신을 보낸다",
    )
    return parser.parse_args(argv)


def resolve_camera_id(source: str, explicit: str | None) -> str:
    """관측에 실을 카메라 ID 를 정한다.

    RTSP 경로 규약이 `<역할>/<camera_id>` 이므로 URL 이 이미 논리 ID 를 싣고
    있다. 같은 사실을 두 곳에서 받으면 둘이 어긋날 수 있어 URL 을 정본으로 쓴다 —
    `inference_common/stream.py` 가 같은 이유로 `camera_id` 를 파생시킨다.

    로컬 카메라 index(`--source 0`)에는 URL 이 없으므로 그때만 직접 받는다.
    """
    if explicit:
        return explicit
    if "://" in source:
        segment = source.rstrip("/").rsplit("/", 1)[-1]
        if segment:
            return segment
    raise SystemExit(
        "카메라 ID 를 정할 수 없습니다. RTSP source 를 쓰거나 --camera-id 를 주세요"
    )


def _post(url: str, payload: dict) -> None:
    """관측 하나를 관제에 올린다. 실패해도 추론 루프를 멈추지 않는다.

    사람이 보이는 동안 관측은 계속 흐른다. 한 번 못 보낸 것 때문에 카메라 읽기가
    멈추면 그 뒤로 아무것도 못 본다. 실패는 찍고 다음 것을 보낸다.
    """
    import urllib.error
    import urllib.request

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=1.0) as response:
            response.read()
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        print(json.dumps({"type": "REPORT_FAILED", "detail": str(error)}), flush=True)


def main(argv: list[str] | None = None) -> int:
    import cv2

    args = parse_args(argv)
    detector_config, posture_config, monitor_config = load_settings(args.config)
    detector = Detector(args.weights, detector_config)
    posture = PostureEstimator(posture_config)
    monitor = FallMonitor(monitor_config)
    throttle = ReportThrottle(ReportPolicy(ttl_ms=args.ttl_ms))
    camera_id = resolve_camera_id(args.source, args.camera_id)

    device = detector.load()
    print(json.dumps({"device": device.to_dict()}, ensure_ascii=False), flush=True)

    capture = cv2.VideoCapture(parse_source(args.source))
    if not capture.isOpened():
        raise RuntimeError(f"영상 source 를 열 수 없습니다: {args.source}")
    started = time.monotonic()
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            timestamp = time.monotonic() - started
            person = detector.detect_person(frame)
            if person is None:
                # 사람이 없으면 자세 기준을 버린다. 다음에 다시 잡혔을 때 그
                # 사이의 간격을 이동으로 세면 정지를 움직임으로 잘못 읽는다.
                posture.reset()
                state = "NO_DETECTION"
            else:
                diagonal = math.hypot(person.mask.shape[1], person.mask.shape[0])
                measurement = posture.measure(person.mask, diagonal)
                if measurement is None:
                    state = "NO_DETECTION"
                else:
                    result = monitor.advance(
                        timestamp,
                        fallen=measurement.low_posture,
                        low_motion=not measurement.moving,
                    )
                    state = result["state"]
                    # 상태가 그대로면 수명의 절반 주기로만 올린다. 15 Hz 를 그대로
                    # 흘리면 TCP 8788 이 관측으로 차고 주행 명령이 뒤로 밀린다.
                    if throttle.should_report(timestamp, f"PERSON:{state}"):
                        observation = {
                            "type": "person_detection",
                            "camera_id": camera_id,
                            "confidence": round(float(person.confidence), 4),
                            "pose_class": state,
                            "ttl_ms": args.ttl_ms,
                            "observed_at_ms": int(time.time() * 1000),
                        }
                        print(json.dumps(observation, ensure_ascii=False), flush=True)
                        if args.report_url:
                            _post(args.report_url, observation)
                    if result["event"]:
                        # 낙상 확정은 사람이 재확인할 사건이라 늘 올린다.
                        print(json.dumps({
                            "type": FALL_EVENT, "state": state, "timestamp": time.time(),
                        }, ensure_ascii=False), flush=True)
            cv2.putText(frame, state, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            if not args.headless:
                cv2.imshow("person + fall monitor", frame)
                if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                    break
    finally:
        capture.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
