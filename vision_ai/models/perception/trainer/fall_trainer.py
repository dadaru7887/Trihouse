"""Train the fall classifier: fit on train, choose on valid, open test once.

    python -m vision_ai.models.perception.trainer.fall_trainer \
        --dataset runs/fall/features.jsonl --out runs/fall \
        --seed 42 --min-recall 0.85 --wandb

Every path is an argument; no dataset location is written into the code or a
default, so another checkout or dataset needs no edit.

Input is one instance per JSONL line, with the features already extracted --
`models/perception/features.py` does that. Building the JSONL from images and
masks is dataset-specific, so no adapter is imposed here.

    {"features": [aspect_ratio, pca_angle, centroid_y,
                  contact_person_iou, contact_obstacle_iou],
     "fallen": true, "split": "train"}

Flow, and the split each stage may look at:

    train   fit the scaler and the logistic regression
    valid   choose the decision threshold -- the model is decided here
    test    measured once at the end, feeding no choice

The threshold is the most precise one that still meets the recall floor.
Recall wins because this is a safety alarm: a false alarm costs a second look,
a miss costs a fall nobody sees. If no candidate meets the floor, the
highest-recall one is kept and `recall_floor_met` is False -- it is never
passed off as met.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from vision_ai.models.perception.features import FEATURE_NAMES
from vision_ai.data_loader.fall.dataset import SPLITS, DatasetError, load_dataset

# The same candidate grid the delivered bundle used.
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
        # On a tie `max` keeps the first, and candidates ascend, so the
        # lowest threshold wins: equal scores pick the more sensitive one.
        # That is the intended direction for a safety alarm, not an accident.
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

    # The threshold is chosen on valid alone; deciding the model ends here.
    threshold, validation, floor_met = _select_threshold(
        splits["valid"][1], probabilities("valid"), min_recall
    )
    # test is measured once and feeds back into no choice.
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
