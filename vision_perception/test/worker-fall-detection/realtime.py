import argparse
import json
import math
import time
from pathlib import Path

import cv2
import yaml

from pipeline.fall_monitor import FallMonitor, MonitorConfig, mask_geometry


def resolve_weights(value: Path) -> Path:
    value = value.expanduser().resolve()
    if value.suffix == ".json":
        selected = json.loads(value.read_text(encoding="utf-8"))
        value = Path(selected["weights"]).expanduser().resolve()
    if not value.is_file():
        raise FileNotFoundError(f"weight가 없습니다: {value}")
    return value


def parse_source(value: str):
    return int(value) if value.isdigit() else value


def main() -> None:
    parser = argparse.ArgumentParser(description="YOLOE LEGO 낙상/무움직임 실시간 PoC")
    parser.add_argument("--weights", type=Path, required=True, help="best.pt 또는 selected_model.json")
    parser.add_argument("--source", default="0", help="카메라 번호, 영상 파일 또는 RTSP URL")
    parser.add_argument("--config", type=Path, default=Path(__file__).parent / "configs/realtime.yaml")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    settings = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    from ultralytics import YOLOE
    model = YOLOE(str(resolve_weights(args.weights)))
    monitor = FallMonitor(MonitorConfig(**settings["monitor"]))
    inference = settings["inference"]
    capture = cv2.VideoCapture(parse_source(args.source))
    if not capture.isOpened():
        raise RuntimeError(f"영상 source를 열 수 없습니다: {args.source}")
    started = time.monotonic()
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            result = model.predict(frame, conf=inference["confidence"], imgsz=inference["image_size"], device=inference["device"], verbose=False)[0]
            state = "NO_DETECTION"
            if result.masks is not None and len(result.masks.data):
                classes = result.boxes.cls.detach().cpu().numpy().astype(int)
                scores = result.boxes.conf.detach().cpu().numpy()
                candidates = [(i, scores[i]) for i, cls in enumerate(classes) if cls == inference["person_class_id"]]
                if candidates:
                    index = max(candidates, key=lambda row: row[1])[0]
                    mask = result.masks.data[index].detach().cpu().numpy() > 0.5
                    geometry = mask_geometry(mask)
                    if geometry:
                        aspect, centroid = geometry
                        update = monitor.update(time.monotonic() - started, aspect, centroid, math.hypot(mask.shape[1], mask.shape[0]))
                        state = update["state"]
                        if update["event"]:
                            print(json.dumps({"type": "WORKER_FALL_CONFIRMATION_REQUEST", "state": state, "timestamp": time.time()}, ensure_ascii=False), flush=True)
            cv2.putText(frame, state, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            if not args.headless:
                cv2.imshow("LEGO fall monitor", frame)
                if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                    break
    finally:
        capture.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
