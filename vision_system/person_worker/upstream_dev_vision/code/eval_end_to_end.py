"""정적 이미지 기준 end-to-end 평가: GT polygon이 아니라 **세그멘테이션 모델이 실제로
찾아낸 mask**로 피처를 뽑아서 분류기에 넣는다. Track B의 metrics.json은 GT polygon
기준이라 탐지 실패가 recall 손실로 안 잡히는데(항상 mask가 있다고 가정), 이 스크립트는
탐지 실패도 "그 인스턴스를 통째로 놓친 것"으로 세서 진짜 실전 recall을 잰다.

GT instance -> 예측 detection 매칭은 IoU 기준(--match-iou 이상인 것 중 최고). 매칭되는
detection이 없으면(탐지 실패) is_fallen인 경우 항상 오답(False Negative) 처리.

사용 예:
    python -m pipeline.eval_end_to_end \\
        --seg-weights ~/Trihouse_segmentation/weights/aug_best.pt \\
        --classifier runs/fallen_classifier_origweights/seed42/fallen_classifier.joblib \\
        --roboflow-export ~/Trihouse_segmentation/fallen_roboflow_export --split test
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import joblib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dataloader.roboflow_labels import load_roboflow_export  # noqa: E402
from trainer.classifier_trainer import (  # noqa: E402
    PromptFeatureExtractor, _box_iou, contact_from_predictions, polygon_to_geometric_features, resolve_device,
)


def _polygon_bbox(polygon: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    pts = np.asarray(polygon, dtype=np.float64)
    return float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())


def main() -> None:
    parser = argparse.ArgumentParser(description="탐지 실패까지 반영한 end-to-end fallen 평가")
    parser.add_argument("--seg-weights", type=Path, required=True)
    parser.add_argument(
        "--decision-mode", choices=("classifier", "rule"), default="classifier",
        help="rule=규칙(aspect_ratio>=--fall-aspect-ratio)만 사용, 분류기 안 씀 -- "
             "같은 탐지 결과 위에서 분류기 자체 기여도를 분리해서 볼 때 씀",
    )
    parser.add_argument("--classifier", type=Path, help="--decision-mode classifier일 때 필수")
    parser.add_argument("--fall-aspect-ratio", type=float, default=0.9, help="--decision-mode rule일 때 임계값")
    parser.add_argument("--roboflow-export", type=Path, required=True)
    parser.add_argument("--split", default="test", choices=("train", "valid", "test"))
    parser.add_argument("--person-class-id", type=int, default=1)
    parser.add_argument("--match-iou", type=float, default=0.3, help="GT-예측 매칭 최소 IoU")
    parser.add_argument(
        "--occluded-videos", nargs="*", default=["dataset_video_20260822_171506"],
        help="가려짐(occlusion)으로 분류할 비디오 prefix 목록 -- 전체/가려짐/안가려짐 나눠서 보고할 때 씀. "
             "fallen_video_split_2026-08-23.md 기준 기본값이 171506(가려짐 진단용 영상).",
    )
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    from ultralytics import YOLOE

    scaler = clf = threshold = use_geometric = use_prompt = use_contact = prompt_extractor = None
    if args.decision_mode == "classifier":
        if args.classifier is None:
            parser.error("--decision-mode classifier면 --classifier 필요")
        bundle = joblib.load(args.classifier)
        scaler, clf = bundle["scaler"], bundle["clf"]
        threshold = bundle.get("threshold", 0.5)
        clf_config = bundle["config"]
        use_geometric = clf_config["use_geometric_features"]
        use_prompt = clf_config["use_prompt_features"]
        use_contact = clf_config.get("use_contact_features", False)

    seg_model = YOLOE(str(args.seg_weights))
    seg_model.to(resolve_device(args.device))

    if args.decision_mode == "classifier" and use_prompt:
        prompt_classes = tuple(clf_config["prompt_classes"])
        phrasings = clf_config.get("prompt_phrasings")
        phrasings = {k: tuple(v) for k, v in phrasings.items()} if phrasings else None
        prompt_extractor = PromptFeatureExtractor(args.seg_weights, prompt_classes, args.device, phrasings)

    records = [r for r in load_roboflow_export(args.roboflow_export) if r.split == args.split]

    from collections import Counter
    per_video = Counter()  # (video, outcome) -> count
    outcomes = []  # (video, occluded, is_fallen, "tp"/"fp"/"fn"/"tn")

    tp = fp = fn = tn = missed_fallen = missed_standing = 0
    for record in records:
        video = record.image_path.name.split("_t0")[0]
        occluded = video in args.occluded_videos
        gt_box = _polygon_bbox(record.polygon)
        result = seg_model.predict(str(record.image_path), imgsz=640, verbose=False)[0]

        best_iou, best_idx = 0.0, None
        if result.boxes is not None:
            for i, cls_id in enumerate(result.boxes.cls.cpu().numpy()):
                if int(cls_id) != args.person_class_id:
                    continue
                box = tuple(result.boxes.xyxyn[i].cpu().numpy().tolist())
                iou = _box_iou(gt_box, box)
                if iou > best_iou:
                    best_iou, best_idx = iou, i

        if best_idx is None or best_iou < args.match_iou:
            # 탐지 실패 -- 이 GT 인스턴스는 분류기까지 갈 기회조차 없었음
            if record.is_fallen:
                fn += 1
                missed_fallen += 1
                per_video[(video, "탐지실패(fallen)")] += 1
                outcomes.append((video, occluded, True, "fn"))
            else:
                tn += 1  # standing을 못 찾은 건 "fallen 아님" 판정과 결과적으로 같은 방향
                missed_standing += 1
                outcomes.append((video, occluded, False, "tn"))
            continue

        polygon = [tuple(p) for p in result.masks.xyn[best_idx].tolist()]
        matched_box = tuple(result.boxes.xyxyn[best_idx].cpu().numpy().tolist())
        if args.decision_mode == "rule":
            aspect_ratio = polygon_to_geometric_features(polygon)[0]
            pred_fallen = aspect_ratio >= args.fall_aspect_ratio
        else:
            parts = []
            if use_geometric:
                parts.append(polygon_to_geometric_features(polygon))
            if use_prompt:
                parts.append(prompt_extractor.extract(record.image_path, polygon))
            if use_contact:
                parts.append(contact_from_predictions(matched_box, result, best_idx, args.person_class_id))
            features = np.concatenate(parts).reshape(1, -1)
            proba = float(clf.predict_proba(scaler.transform(features))[0, 1])
            pred_fallen = proba >= threshold

        if record.is_fallen and pred_fallen:
            tp += 1
            outcomes.append((video, occluded, True, "tp"))
        elif record.is_fallen and not pred_fallen:
            fn += 1
            per_video[(video, "탐지는됐는데분류실패(fallen)")] += 1
            outcomes.append((video, occluded, True, "fn"))
        elif not record.is_fallen and pred_fallen:
            fp += 1
            outcomes.append((video, occluded, False, "fp"))
        else:
            tn += 1
            outcomes.append((video, occluded, False, "tn"))

    def _report(label: str, subset: list[tuple]) -> None:
        s_tp = sum(1 for *_, o in subset if o == "tp")
        s_fp = sum(1 for *_, o in subset if o == "fp")
        s_fn = sum(1 for *_, o in subset if o == "fn")
        s_fallen = s_tp + s_fn
        s_precision = s_tp / (s_tp + s_fp) if (s_tp + s_fp) else 0.0
        s_recall = s_tp / s_fallen if s_fallen else 0.0
        print(f"  [{label}] n={len(subset)} fallen={s_fallen} -> precision={s_precision:.3f} recall={s_recall:.3f} "
              f"(TP={s_tp} FP={s_fp} FN={s_fn})")

    print(f"[end-to-end, {args.split}] n={len(records)}")
    print(f"  탐지 실패로 통째로 놓친 것: fallen {missed_fallen}개, standing {missed_standing}개")
    if per_video:
        print("  --- 비디오별 fallen 손실 breakdown ---")
        for (video, outcome), count in sorted(per_video.items()):
            print(f"    {video} / {outcome}: {count}개")
    print("  --- 전체/가려짐/안가려짐 breakdown ---")
    _report("전체", outcomes)
    _report("가려짐", [o for o in outcomes if o[1]])
    _report("안가려짐", [o for o in outcomes if not o[1]])
    print(f"  TP={tp} FP={fp} FN={fn} TN={tn}")


if __name__ == "__main__":
    main()
