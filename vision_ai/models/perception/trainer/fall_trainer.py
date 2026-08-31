"""낙상 분류기 학습 진입점 — train 으로 맞추고, valid 로 고르고, test 는 마지막에 한 번.

    python -m vision_ai.models.perception.trainer.fall_trainer \
        --dataset /path/to/features.jsonl \
        --out runs/fallen_classifier \
        --seed 42 --min-recall 0.85

**경로는 전부 인자다.** 데이터셋 위치를 코드에도 기본값에도 넣지 않는다 — 다른
체크아웃이나 다른 데이터셋으로 옮길 때 코드를 고치지 않아야 한다.

입력은 피처가 이미 뽑힌 JSONL 한 줄에 한 인스턴스다. 피처를 뽑는 쪽은
`vision_ai/models/perception/features.py` 이고, 원본 이미지·mask 에서 이 JSONL 을 만드는
어댑터는 데이터셋 형식마다 다르므로 여기서 강제하지 않는다.

    {"features": [aspect_ratio, pca_angle, centroid_y,
                  contact_person_iou, contact_obstacle_iou],
     "fallen": true, "split": "train"}

`split` 은 `train` / `valid` / `test` 셋뿐이다.

- `train`  — scaler 와 logistic regression 을 맞춘다
- `valid`  — 결정 임계값을 고른다. **여기까지만 보고 모델을 정한다**
- `test`   — 마지막에 한 번 재고 어떤 선택에도 쓰지 않는다

임계값은 recall 바닥을 만족하는 것 중 precision 이 가장 높은 값이다. 안전 경보라
recall 을 우선한다 — 오탐은 사람이 한 번 더 보는 비용이지만 미탐은 실제 낙상을
놓치는 비용이다. 바닥을 만족하는 후보가 없으면 recall 이 가장 높은 값으로 두고
`recall_floor_met` 을 False 로 남긴다. 조용히 통과시키지 않는다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from vision_ai.models.perception.features import FEATURE_NAMES
from vision_ai.data_loader.fall.dataset import SPLITS, DatasetError, load_dataset

# 배달본이 쓴 후보 격자와 같다.
THRESHOLD_CANDIDATES = [round(0.05 + 0.05 * step, 2) for step in range(19)]


def _scores(labels: list[int], predictions: list[int]) -> dict[str, float]:
    true_positive = sum(1 for y, p in zip(labels, predictions) if y == 1 and p == 1)
    false_positive = sum(1 for y, p in zip(labels, predictions) if y == 0 and p == 1)
    false_negative = sum(1 for y, p in zip(labels, predictions) if y == 1 and p == 0)
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    return {
        "precision": round(precision, 6), "recall": round(recall, 6),
        "true_positive": true_positive, "false_positive": false_positive,
        "false_negative": false_negative, "support": sum(labels),
    }


def _select_threshold(labels: list[int], probabilities: list[float],
                      min_recall: float) -> tuple[float, dict[str, float], bool]:
    rows = []
    for candidate in THRESHOLD_CANDIDATES:
        scored = _scores(labels, [1 if p >= candidate else 0 for p in probabilities])
        rows.append((candidate, scored))
    passing = [row for row in rows if row[1]["recall"] >= min_recall]
    if passing:
        # 동점이면 `max` 가 앞의 것을 남기고 후보는 오름차순이므로 **가장 낮은**
        # 임계값이 이긴다. 즉 성능이 같으면 더 민감한 쪽을 고른다 — 안전 경보에서
        # 의도한 방향이다. 우연이 아니라 선택이다.
        threshold, scored = max(passing, key=lambda row: (row[1]["precision"], row[1]["recall"]))
        return threshold, scored, True
    threshold, scored = max(rows, key=lambda row: (row[1]["recall"], row[1]["precision"]))
    return threshold, scored, False


def train_classifier(dataset_path: Path, out_dir: Path, *, seed: int = 42,
                     min_recall: float = 0.85) -> dict[str, Any]:
    import joblib
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    splits = load_dataset(Path(dataset_path))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    train_x = np.asarray(splits["train"][0], dtype=np.float64)
    train_y = np.asarray(splits["train"][1], dtype=np.int64)

    scaler = StandardScaler().fit(train_x)
    model = LogisticRegression(max_iter=1000, random_state=seed)
    model.fit(scaler.transform(train_x), train_y)

    def probabilities(split: str) -> list[float]:
        features = np.asarray(splits[split][0], dtype=np.float64)
        return [float(p) for p in model.predict_proba(scaler.transform(features))[:, 1]]

    # 임계값은 valid 로만 고른다. 여기까지가 "모델을 정하는" 구간이다.
    threshold, validation, floor_met = _select_threshold(
        splits["valid"][1], probabilities("valid"), min_recall
    )
    # test 는 이제 딱 한 번. 어떤 선택에도 되먹임되지 않는다.
    test_probabilities = probabilities("test")
    test = _scores(splits["test"][1], [1 if p >= threshold else 0 for p in test_probabilities])

    bundle_path = out_dir / "fallen_classifier.joblib"
    joblib.dump({
        "scaler": scaler, "clf": model, "threshold": threshold,
        "config": {"use_geometric_features": True, "use_prompt_features": False,
                   "use_contact_features": True, "feature_names": list(FEATURE_NAMES)},
    }, bundle_path)

    result = {
        "bundle": str(bundle_path),
        "threshold": threshold,
        "recall_floor": min_recall,
        "recall_floor_met": floor_met,
        "seed": seed,
        "coefficients": [round(float(value), 8) for value in model.coef_[0]],
        "feature_names": list(FEATURE_NAMES),
        "validation": validation,
        "test": test,
        "dataset": {
            "path": str(Path(dataset_path).resolve()),
            "counts": {split: len(splits[split][1]) for split in SPLITS},
            "fallen": {split: int(sum(splits[split][1])) for split in SPLITS},
        },
    }
    (out_dir / "metrics.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    """Define the command line: which features, where to write, how strict."""
    parser = argparse.ArgumentParser(
        description="Train the fall classifier: fit on train, choose on valid, "
                    "open test once"
    )
    parser.add_argument("--dataset", type=Path, required=True,
                        help="Feature JSONL with the fields features/fallen/split")
    parser.add_argument("--out", type=Path, required=True,
                        help="Directory for the bundle and metrics.json")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-recall", type=float, default=0.85,
                        help="Recall floor the chosen threshold must meet. Recall "
                             "wins over precision here: a false alarm costs a "
                             "second look, a miss costs a fall nobody sees")
    parser.add_argument("--wandb", action="store_true",
                        help="Mirror metrics to Weights & Biases")
    parser.add_argument("--wandb-project", default="trihouse-vision",
                        help="wandb project to log the run into")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Train the classifier and report what it chose."""
    from vision_ai.utils.run_logging import Tracker, setup_logging

    args = build_parser().parse_args(argv)
    logger = setup_logging(args.out)
    logger.info("fall classifier | dataset=%s | seed=%s | min_recall=%.2f",
                args.dataset, args.seed, args.min_recall)
    tracker = Tracker(enabled=args.wandb, project=args.wandb_project,
                      name=f"fall-{args.out.name}",
                      config={"dataset": str(args.dataset), "seed": args.seed,
                              "min_recall": args.min_recall},
                      run_dir=args.out)
    try:
        result = train_classifier(args.dataset, args.out, seed=args.seed,
                                  min_recall=args.min_recall)
    except DatasetError as error:
        logger.error("DATASET failed | %s", error)
        tracker.finish()
        return 2

    logger.info("threshold=%.4f | recall_floor_met=%s",
                result["threshold"], result["recall_floor_met"])
    for split in ("validation", "test"):
        logger.info("%s %s", split.upper(),
                    " ".join(f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"
                             for k, v in sorted(result[split].items())))
    if not result["recall_floor_met"]:
        logger.warning("no threshold met the recall floor; kept the highest-recall one")
    tracker.summary({
        "threshold": result["threshold"],
        "recall_floor_met": result["recall_floor_met"],
        **{f"val/{k}": v for k, v in result["validation"].items()},
        **{f"test/{k}": v for k, v in result["test"].items()},
    })
    tracker.finish()
    logger.info("bundle written to %s", result["bundle"])
    print(json.dumps({
        "threshold": result["threshold"],
        "recall_floor_met": result["recall_floor_met"],
        "validation": result["validation"],
        "test": result["test"],
        "bundle": result["bundle"],
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
