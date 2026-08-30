"""Track B(정지 이미지 분류기) -> Track A(세그멘테이션) -> 상태머신(fall_monitor.py)을
실제 영상에 프레임 단위로 연결하는 파이프라인. 지금까지는 이 세 조각이 따로
존재했음 -- 분류기는 정지 이미지 precision/recall만 냈고, 상태머신은 aspect_ratio
규칙 하나로만 fallen을 판정했음(둘이 안 이어져 있었음). 이 스크립트가 그 연결.

fallen 판정 = 분류기(proba>=classifier_threshold)만 씀(규칙 OR는 뺌 -- 실측 확인 결과
분류기 판정 영역이 규칙을 완전히 포함해서 무의미한 결합이었음). 안전 경보 시스템 표준
관행(recall 우선): 이 파이프라인은 최종 판정자가 아니라 관제 확인 요청
(EMERGENCY_CANDIDATE)만 만들기 때문에, 오탐 비용은 사람이 한 번 더 보는 정도지만 미탐
비용은 실제 낙상을 놓치는 것. 정확한 근거: [[project_fallen_detection_options_and_progress]].

**사람마다 독립된 추적/상태머신 (2026-08-24)**: `model.track(persist=True)`로 프레임을
넘나드는 track_id를 부여받아서, `dict[track_id, FallMonitor]`로 사람별 상태를 완전히
분리함. 원본 참고 구현(dadaru7887/Trihouse `feat/pinky-edge-agent` 브랜치
`vision_system/person_worker/policy.py`의 `PersonPolicy`)이 이미 이 설계였음 -- "두 사람이
한 화면에 있으면 한 사람의 회복이 다른 사람의 증거를 지워서는 안 된다"는 원칙. 이전 버전은
매 프레임 "분류기 proba 최고인 사람 1명"만 골라 공유 FallMonitor 하나에 넣는 임시방편이었고,
그게 다중 인원 영상에서 애매한 지연들의 원인이었을 가능성이 있음.

사용 예:
    python -m pipeline.video_monitor \\
        --classifier runs/fallen_classifier/run/fallen_classifier.joblib \\
        --video ~/fallen_detection/dataset_video_20260822_162744.mp4 \\
        --out runs/fallen_classifier/video_monitor/re_162744.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from math import hypot
from pathlib import Path

import joblib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.fall_monitor import FallMonitor, MonitorConfig  # noqa: E402
from trainer.classifier_trainer import (  # noqa: E402
    PromptFeatureExtractor, contact_from_predictions, polygon_to_geometric_features, resolve_device,
)


def _box_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


class VideoFallPipeline:
    def __init__(
        self, seg_weights: Path, classifier_path: Path, device: str = "auto",
        person_class_id: int = 1, monitor_config: MonitorConfig | None = None,
        classifier_threshold: float | None = None, track_timeout_seconds: float = 3.0,
    ) -> None:
        from ultralytics import YOLOE

        bundle = joblib.load(classifier_path)
        self.scaler, self.clf = bundle["scaler"], bundle["clf"]
        clf_config = bundle["config"]  # 학습 때 쓴 ClassifierConfig.to_dict() -- 피처 정의를 그대로 재사용
        # classifier_threshold를 안 주면 학습 시 k-fold로 고른 threshold를 그대로 씀
        # (bundle["threshold"], train()이 저장). 0.5 같은 임의값으로 덮어쓰지 않기 위함.
        if classifier_threshold is None:
            classifier_threshold = bundle.get("threshold", 0.5)
        self.use_geometric = clf_config["use_geometric_features"]
        self.use_prompt = clf_config["use_prompt_features"]
        self.use_contact = clf_config.get("use_contact_features", False)
        self.classifier_threshold = classifier_threshold
        self.person_class_id = person_class_id

        self.seg_model = YOLOE(str(seg_weights))
        self.seg_model.to(resolve_device(device))

        self.prompt_extractor = None
        if self.use_prompt:
            prompt_classes = tuple(clf_config["prompt_classes"])
            phrasings = clf_config.get("prompt_phrasings")
            phrasings = {k: tuple(v) for k, v in phrasings.items()} if phrasings else None
            # 프롬프트용 별도 인스턴스 -- set_classes가 모델의 분류 head를 바꿔버려서
            # person/obstacle을 찾는 seg_model과 같이 쓰면 안 됨.
            self.prompt_extractor = PromptFeatureExtractor(seg_weights, prompt_classes, device, phrasings)

        self.monitor_config = monitor_config or MonitorConfig()
        # track_id별 독립 상태 -- 한 사람의 회복이 다른 사람의 증거를 지우지 않게 함
        # (dadaru7887/Trihouse feat/pinky-edge-agent의 PersonPolicy 설계, 2026-08-24
        # 도입). 짧은 끊김(모션블러, 1~2프레임 미검출)은 ultralytics 내장 트래커가
        # 알아서 같은 track_id를 유지해주지만, 긴 끊김(카메라 전환 등) 뒤에는 새
        # track_id가 부여되면서 그 사람 몫 모니터가 새로 시작됨 -- 재식별(ReID) 없이는
        # 못 푸는 한계로 인정하고 감(사용자와 논의, 2026-08-24).
        self.monitors: dict[int, FallMonitor] = {}
        self.last_centroids: dict[int, tuple[float, float]] = {}
        self.last_aspect_ratios: dict[int, float] = {}
        self.last_seen: dict[int, float] = {}
        self.track_timeout_seconds = track_timeout_seconds

    def _all_tracked_persons(
        self, result,
    ) -> list[tuple[int, list[tuple[float, float]], tuple[float, float, float, float], int]]:
        """(track_id, polygon, box, result내_index) 목록. track_id가 없으면(추적 실패)
        그 detection은 이번 프레임에서 건너뜀 -- track_id 없이는 어느 모니터에
        넣을지 알 수 없음."""
        if result.boxes is None or result.masks is None or result.boxes.id is None:
            return []
        ids = result.boxes.id.cpu().numpy()
        out = []
        for i, cls_id in enumerate(result.boxes.cls.cpu().numpy()):
            if int(cls_id) != self.person_class_id:
                continue
            polygon = [tuple(p) for p in result.masks.xyn[i].tolist()]
            box = tuple(result.boxes.xyxyn[i].cpu().numpy().tolist())
            out.append((int(ids[i]), polygon, box, i))
        return out

    def _score_person(self, frame: np.ndarray, result, detection) -> tuple[float, float, tuple[float, float]]:
        """(fallen 확률, aspect_ratio, centroid) 하나의 사람 detection에 대해 계산."""
        polygon, box, idx = detection
        aspect_ratio = float(polygon_to_geometric_features(polygon)[0])
        pts = np.asarray(polygon, dtype=np.float64)
        centroid = (float(pts[:, 0].mean()), float(pts[:, 1].mean()))

        feature_parts = []
        if self.use_geometric:
            feature_parts.append(polygon_to_geometric_features(polygon))
        if self.use_prompt:
            feature_parts.append(self.prompt_extractor.extract(frame, polygon))
        if self.use_contact:
            feature_parts.append(contact_from_predictions(box, result, idx, self.person_class_id))
        features = np.concatenate(feature_parts).reshape(1, -1)
        proba = float(self.clf.predict_proba(self.scaler.transform(features))[0, 1])
        return proba, aspect_ratio, centroid

    def process_frame(self, frame: np.ndarray, timestamp: float) -> dict:
        result = self.seg_model.track(
            frame, imgsz=640, verbose=False, persist=True, tracker="bytetrack.yaml",
        )[0]
        tracked = self._all_tracked_persons(result)
        seen_ids = {track_id for track_id, *_ in tracked}

        # 이번 프레임에 안 보인(추적 실패했거나 진짜 없는) 기존 track들 -- state/since는
        # 안 건드리고 recovery_since만 리셋(note_no_detection, fall_monitor.py 참고).
        for track_id, monitor in self.monitors.items():
            if track_id not in seen_ids:
                monitor.note_no_detection()

        persons: dict[int, dict] = {}
        for track_id, polygon, box, idx in tracked:
            proba, aspect_ratio, centroid = self._score_person(frame, result, (polygon, box, idx))
            rule_fallen = aspect_ratio >= self.monitor_config.fall_aspect_ratio
            classifier_fallen = proba >= self.classifier_threshold
            fallen = classifier_fallen

            last_centroid = self.last_centroids.get(track_id)
            motion = 0.0 if last_centroid is None else hypot(
                centroid[0] - last_centroid[0], centroid[1] - last_centroid[1]
            )  # 정규화 좌표라 frame_diagonal은 sqrt(2) 고정
            motion /= 2 ** 0.5
            self.last_centroids[track_id] = centroid

            # centroid(위치) 이동만 보면 "제자리에서 일어나는" 동작을 안 움직임으로
            # 오판함(2026-08-24 162744 실측) -- aspect_ratio가 프레임 사이 크게
            # 바뀌는 중이면 자세가 변하고 있는 거라 low_motion에서 제외.
            last_aspect_ratio = self.last_aspect_ratios.get(track_id)
            posture_change = 0.0 if last_aspect_ratio is None else abs(aspect_ratio - last_aspect_ratio)
            self.last_aspect_ratios[track_id] = aspect_ratio
            self.last_seen[track_id] = timestamp

            low_motion = (
                motion <= self.monitor_config.motion_threshold
                and posture_change <= self.monitor_config.posture_change_threshold
            )
            monitor = self.monitors.setdefault(track_id, FallMonitor(self.monitor_config))
            state = monitor.advance(timestamp, fallen=fallen, low_motion=low_motion)
            state.update({
                "track_id": track_id, "no_detection": False, "aspect_ratio": aspect_ratio,
                "classifier_proba": proba, "rule_fallen": rule_fallen,
                "classifier_fallen": classifier_fallen, "motion": motion, "posture_change": posture_change,
            })
            persons[track_id] = state

        # 오래(track_timeout_seconds 이상) 안 보인 track은 아예 정리 -- 재식별 없이는
        # "같은 사람이 돌아왔다"를 확신 못 하므로, 다시 나타나면 새 모니터로 새출발함
        # (알려진 한계, 2026-08-24 사용자와 논의).
        stale = [tid for tid, seen in self.last_seen.items() if timestamp - seen > self.track_timeout_seconds]
        for tid in stale:
            self.monitors.pop(tid, None)
            self.last_centroids.pop(tid, None)
            self.last_seen.pop(tid, None)

        return {
            "no_detection": not tracked, "persons": persons,
            "event": any(p["event"] for p in persons.values()),
        }


def main() -> None:
    import cv2

    parser = argparse.ArgumentParser(description="분류기+규칙+상태머신을 영상에 프레임 단위로 실행")
    parser.add_argument("--seg-weights", type=Path, required=True)
    parser.add_argument("--classifier", type=Path, required=True, help="fallen_classifier.joblib 경로")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="프레임별 상태를 저장할 JSONL")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--person-class-id", type=int, default=1)
    parser.add_argument(
        "--classifier-threshold", type=float, default=None,
        help="생략하면 학습 때 k-fold로 고른 threshold(joblib에 저장됨)를 씀",
    )
    parser.add_argument("--fall-aspect-ratio", type=float, default=0.9)
    parser.add_argument("--fall-confirm-seconds", type=float, default=1.0)
    parser.add_argument("--immobile-seconds", type=float, default=5.0)
    parser.add_argument("--motion-threshold", type=float, default=0.015)
    parser.add_argument("--recovery-confirm-seconds", type=float, default=1.0)
    args = parser.parse_args()

    monitor_config = MonitorConfig(
        fall_aspect_ratio=args.fall_aspect_ratio, fall_confirm_seconds=args.fall_confirm_seconds,
        immobile_seconds=args.immobile_seconds, motion_threshold=args.motion_threshold,
        recovery_confirm_seconds=args.recovery_confirm_seconds,
    )
    pipeline = VideoFallPipeline(
        args.seg_weights, args.classifier, args.device, args.person_class_id,
        monitor_config, args.classifier_threshold,
    )

    cap = cv2.VideoCapture(str(args.video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    events = []
    with args.out.open("w", encoding="utf-8") as f:
        frame_idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            timestamp = frame_idx / fps
            result = pipeline.process_frame(frame, timestamp)
            result["timestamp"] = timestamp
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
            if result.get("event"):
                fired_ids = [tid for tid, p in result["persons"].items() if p.get("event")]
                events.append((timestamp, fired_ids))
                print(f"[EMERGENCY_CANDIDATE] t={timestamp:.2f}s track_id={fired_ids}")
            frame_idx += 1
    cap.release()
    print(f"[결과] {frame_idx}프레임 처리, EMERGENCY_CANDIDATE {len(events)}회: {events}")
    print(f"로그: {args.out}")


if __name__ == "__main__":
    main()
