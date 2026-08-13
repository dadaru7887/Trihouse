from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BinaryCounts:
    tp: int = 0
    fp: int = 0
    fn: int = 0


def _divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def instance_metrics(counts: BinaryCounts) -> dict[str, float | int]:
    precision = _divide(counts.tp, counts.tp + counts.fp)
    recall = _divide(counts.tp, counts.tp + counts.fn)
    return {"tp": counts.tp, "fp": counts.fp, "fn": counts.fn, "precision": precision, "recall": recall, "f1": _divide(2 * precision * recall, precision + recall)}


def mask_metrics(prediction: np.ndarray, target: np.ndarray) -> dict[str, float | int]:
    prediction, target = prediction.astype(bool), target.astype(bool)
    tp = int(np.logical_and(prediction, target).sum())
    fp = int(np.logical_and(prediction, ~target).sum())
    fn = int(np.logical_and(~prediction, target).sum())
    tn = int(np.logical_and(~prediction, ~target).sum())
    return {
        "pixel_tp": tp, "pixel_fp": fp, "pixel_fn": fn, "pixel_tn": tn,
        "mask_iou": _divide(tp, tp + fp + fn), "dice_f1": _divide(2 * tp, 2 * tp + fp + fn),
        "pixel_accuracy": _divide(tp + tn, tp + fp + fn + tn),
    }
