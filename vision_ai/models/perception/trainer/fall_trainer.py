"""Train the fall classifier: fit on train, choose on valid, open test once.

    python -m vision_ai.models.perception.trainer.fall_trainer \
        --dataset runs/fall/features.jsonl --out runs/fall \
        --seed 42 --min-recall 0.85 --wandb

Every path is an argument; no dataset location is written into the code or a
default, so another checkout or dataset needs no edit.

Input is one instance per JSONL line, as `data_loader/fall/build_features.py`
writes it; FEATURE_NAMES from `models/perception/features.py` are read by name:

    {"features": {"aspect_ratio": 1.3, "axis_horizontality": 0.8},
     "fallen": true, "split": "train", "episode": "20260822_162137"}

Flow, and the split each stage may look at:

    train   fit OR and SUM (fall_model.py), keep the one with the higher
            leave-one-episode-out AUC across train episodes
    valid   choose the decision threshold -- the model is decided here
    test    measured once at the end, feeding no choice

The bundle holds {"model", "kind", "feature_names", "threshold"}, the shape
`models/perception/fall_classifier.py` loads.

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
from vision_ai.models.perception.trainer.fall_model import (
    SumModel, cross_validate, fit_candidates,
)

# Formula kept when cross-validation cannot decide: OR held fewer false
# positives than SUM at equal recall on ground-truth masks (fall_model.py).
DEFAULT_KIND = "or"

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


def _named_rows(dataset_path: Path) -> list[dict[str, Any]]:
    """JSONL rows with features keyed by name and an episode for cross-validation.

    `load_dataset` has already refused malformed lines, so this only reshapes.
    A row without an episode gets its own, which makes leave-one-episode-out
    impossible and falls back to the default formula.
    """
    rows = []
    text = Path(dataset_path).read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        values = record["features"]
        if not isinstance(values, dict):
            values = dict(zip(FEATURE_NAMES, values))
        rows.append({"features": {name: float(values[name]) for name in FEATURE_NAMES},
                     "fallen": bool(record.get("fallen")), "split": record["split"],
                     "episode": str(record.get("episode", f"row{number}"))})
    return rows


def _parameters(model: Any) -> list[float]:
    """Fitted coefficients of either formula, for reproducibility checks."""
    if isinstance(model, SumModel):
        return [round(float(v), 8) for v in (*model.weights, model.bias)]
    return [round(float(v), 8) for mode in model.modes.values() for v in (mode.weight, mode.bias)]


def _choose_kind(train: list[dict[str, Any]]) -> tuple[str, dict]:
    """Pick OR or SUM by leave-one-episode-out AUC on train alone.

    Falls back to DEFAULT_KIND when fewer than two train episodes hold both
    classes, since a held-out episode needs both for an AUC.
    """
    report = cross_validate(train)
    scored = {name: entry for name, entry in report.items() if entry["per_episode"]}
    if len(scored) < 2 or min(len(e["per_episode"]) for e in scored.values()) < 2:
        return DEFAULT_KIND, {"method": "default", "reason": "too few mixed-class episodes",
                              "cv": report}
    # Higher mean AUC wins; on a tie the default formula is kept.
    best = max(scored, key=lambda name: (scored[name]["mean_auc"], name == DEFAULT_KIND))
    return best, {"method": "leave_one_episode_out", "cv": report}


def train_classifier(dataset_path: Path, out_dir: Path, *, seed: int = 42,
                     min_recall: float = 0.85) -> dict[str, Any]:
    """Fit both formulas on train, keep one, threshold on valid, score test once."""
    import joblib

    load_dataset(Path(dataset_path))          # refuses an unscoreable dataset
    rows = _named_rows(Path(dataset_path))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    by_split = {split: [r for r in rows if r["split"] == split] for split in SPLITS}

    # Both formulas see train only; the choice between them too.
    candidates = fit_candidates(by_split["train"])
    kind, selection = _choose_kind(by_split["train"])
    model = candidates[kind]

    def labels(split: str) -> list[int]:
        return [int(r["fallen"]) for r in by_split[split]]

    def probabilities(split: str) -> list[float]:
        return [model.score(r["features"]) for r in by_split[split]]

    # The threshold is chosen on valid alone; deciding the model ends here.
    threshold, validation, floor_met = _select_threshold(
        labels("valid"), probabilities("valid"), min_recall
    )
    # test is measured once and feeds back into no choice.
    test = _scores(labels("test"), [1 if p >= threshold else 0 for p in probabilities("test")])

    bundle_path = out_dir / "fallen_classifier.joblib"
    # The shape FallenClassifier.load reads: a model scored by feature name.
    joblib.dump({"model": model, "kind": kind, "feature_names": list(FEATURE_NAMES),
                 "threshold": threshold, "seed": seed}, bundle_path)

    result = {
        "bundle": str(bundle_path),
        "kind": kind,
        "selection": selection,
        "threshold": threshold,
        "recall_floor": min_recall,
        "recall_floor_met": floor_met,
        "seed": seed,
        "coefficients": _parameters(model),
        "dropped_features": list(model.dropped),
        "feature_names": list(FEATURE_NAMES),
        "validation": validation,
        "test": test,
        "dataset": {
            "path": str(Path(dataset_path).resolve()),
            "counts": {split: len(by_split[split]) for split in SPLITS},
            "fallen": {split: sum(labels(split)) for split in SPLITS},
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
