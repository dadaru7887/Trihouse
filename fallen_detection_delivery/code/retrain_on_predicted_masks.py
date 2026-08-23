"""분류기를 GT polygon이 아니라 **세그멘테이션이 실제로 예측한 mask**로 재학습.

기존 `trainer.classifier_trainer.train()`은 GT polygon에서 기하학적 피처를 뽑는데,
실전에서는 예측 mask(경계가 GT보다 약간 잘리거나 뭉개짐)를 쓰므로 aspect_ratio 분포가
살짝 다르다. GT 기준으로 고른 threshold가 예측 mask 기준으로는 최적이 아닐 수 있어서,
train+valid 풀을 예측 mask로 다시 만들어 k-fold로 threshold를 재선택한다.

탐지 자체가 실패한 인스턴스(GT와 매칭되는 예측이 없는 경우)는 이 풀에서 **제외**한다 --
이건 stage① 문제(세그멘테이션 recall)이지 stage②(분류기 정확도) 재보정 범위가 아니고,
데이터 추가 없이는 못 고치는 부분이라 여기 섞으면 threshold 선택이 왜곡된다.

test는 여전히 한 번도 안 보고, 마지막에 pipeline/eval_end_to_end.py로 별도 확인한다.

사용 예:
    python -m pipeline.retrain_on_predicted_masks \\
        --seg-weights <A 대표모델 best.pt> \\
        --roboflow-export ~/Trihouse_segmentation/fallen_roboflow_export \\
        --out runs/fallen_classifier_predicted_mask/seed42/fallen_classifier.joblib
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
    _box_iou, _polygon_bbox, _select_threshold, contact_from_predictions,
    polygon_to_geometric_features, resolve_device,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="예측 mask 기준으로 threshold 재선택")
    parser.add_argument("--seg-weights", type=Path, required=True)
    parser.add_argument("--roboflow-export", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--person-class-id", type=int, default=1)
    parser.add_argument("--match-iou", type=float, default=0.3)
    parser.add_argument("--no-contact", action="store_true", help="사람-사람/사람-장애물 접촉 피처 끄기")
    parser.add_argument("--n-folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-recall", type=float, default=0.85)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    from ultralytics import YOLOE
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import precision_score, recall_score
    from sklearn.model_selection import StratifiedKFold
    from sklearn.preprocessing import StandardScaler

    seg_model = YOLOE(str(args.seg_weights))
    seg_model.to(resolve_device(args.device))

    records = [
        r for r in load_roboflow_export(args.roboflow_export) if r.split in ("train", "valid")
    ]

    features, labels = [], []
    n_missed = 0
    for record in records:
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
            n_missed += 1
            continue  # 탐지 실패 -- 이 재보정 범위 밖(stage① 문제)
        polygon = [tuple(p) for p in result.masks.xyn[best_idx].tolist()]
        matched_box = tuple(result.boxes.xyxyn[best_idx].cpu().numpy().tolist())
        parts = [polygon_to_geometric_features(polygon)]
        if not args.no_contact:
            parts.append(contact_from_predictions(matched_box, result, best_idx, args.person_class_id))
        features.append(np.concatenate(parts))
        labels.append(1 if record.is_fallen else 0)

    x_pool = np.stack(features)
    y_pool = np.array(labels, dtype=np.int64)
    n_fallen_pool = int(y_pool.sum())
    print(f"[풀] train+valid {len(records)}개 중 탐지실패 {n_missed}개 제외 -> {len(y_pool)}개 "
          f"(fallen {n_fallen_pool}개)")

    def make_clf():
        return LogisticRegression(max_iter=1000, random_state=args.seed, class_weight="balanced")

    n_splits = max(2, min(args.n_folds, n_fallen_pool, len(y_pool) - n_fallen_pool))
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=args.seed)
    oof_proba = np.zeros(len(y_pool))
    for fold_train_idx, fold_val_idx in skf.split(x_pool, y_pool):
        fold_scaler = StandardScaler().fit(x_pool[fold_train_idx])
        fold_clf = make_clf()
        fold_clf.fit(fold_scaler.transform(x_pool[fold_train_idx]), y_pool[fold_train_idx])
        oof_proba[fold_val_idx] = fold_clf.predict_proba(fold_scaler.transform(x_pool[fold_val_idx]))[:, 1]
    threshold, threshold_report = _select_threshold(y_pool, oof_proba, args.min_recall)

    scaler = StandardScaler().fit(x_pool)
    clf = make_clf()
    clf.fit(scaler.transform(x_pool), y_pool)

    print(f"[CV] {n_splits}-fold -> threshold={threshold:.2f} "
          f"(CV precision={threshold_report['precision']:.3f}, recall={threshold_report['recall']:.3f})")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "scaler": scaler, "clf": clf, "threshold": threshold,
        "config": {
            "use_geometric_features": True, "use_prompt_features": False,
            "use_contact_features": not args.no_contact,
            "prompt_classes": [], "prompt_phrasings": None,
        },
    }, args.out)
    print(f"저장됨: {args.out}")


if __name__ == "__main__":
    main()
