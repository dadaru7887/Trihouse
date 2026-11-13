"""The two candidate fall formulas, fitted side by side so the data can choose.

    from vision_ai.models.perception.trainer.fall_model import (
        fit_candidates, cross_validate)

    models = fit_candidates(rows)            # {"or": OrModel, "sum": SumModel}
    report = cross_validate(rows)            # leave-one-episode-out AUC for each

Two ways to turn the shape features into one number:

    SumModel  one logistic regression over every feature at once. The features
              are averaged, so a posture only one of them can see is diluted.
    OrModel   one logistic regression per feature, combined with max. Each is
              a detector for one fall posture; a fall is evidenced when any
              fires.

On ground-truth masks OR held 13 false positives where the sum held 25, at
equal recall, because catching the diagonal falls no longer required dropping
the aspect threshold far enough to sweep in standing people. That measurement
does not transfer automatically: the deployed model is fitted on the
segmentation model's masks, whose edges are cut and smoothed, so both are
fitted on every run and compared again. The deployed bundle is SUM regardless
(fall_trainer.KIND): it is the formula the design describes, and the measured
gap was too small to justify deploying the other.

Comparison is leave-one-episode-out, never a single split. Adjacent frames of
one recording are near identical, and a 21-positive validation split ranked
the two formulas the other way round before cross-validation corrected it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from vision_ai.models.perception.features import FEATURE_NAMES, combine_modes

# A feature whose training spread is under this carries no signal to scale, and
# StandardScaler would divide by it: contact_person_iou was zero in 97% of rows
# and a 0.17 value at inference standardised to 18.8, swamping every other term.
MIN_TRAINING_STD = 1e-3


@dataclass
class ModeModel:
    """One calibrated detector: a feature, its scaler, and a logistic fit."""

    feature: str
    mean: float
    std: float
    weight: float
    bias: float

    def probability(self, value: float) -> float:
        """Probability this one feature assigns to the instance being fallen."""
        import numpy as np

        z = (value - self.mean) / self.std
        return float(1.0 / (1.0 + np.exp(-(self.weight * z + self.bias))))

    def crossing_point(self) -> float:
        """The feature value where this mode reaches 0.5, in original units.

        Reported because a coefficient is meaningless without the scaler it
        was fitted with, while this is directly comparable to a raw feature.
        """
        return self.mean + self.std * (-self.bias / self.weight)


@dataclass
class OrModel:
    """Per-mode detectors combined with max."""

    modes: dict[str, ModeModel]
    dropped: tuple[str, ...] = ()

    def score(self, features: Mapping[str, float]) -> float:
        return combine_modes({name: model.probability(features[name])
                              for name, model in self.modes.items()})

    def crossing_points(self) -> dict[str, float]:
        return {name: model.crossing_point() for name, model in self.modes.items()}


@dataclass
class SumModel:
    """One logistic regression over every feature at once."""

    features: tuple[str, ...]
    mean: Any
    std: Any
    weights: Any
    bias: float
    dropped: tuple[str, ...] = ()

    def score(self, features: Mapping[str, float]) -> float:
        import numpy as np

        x = np.array([features[name] for name in self.features], dtype=float)
        z = (x - self.mean) / self.std
        return float(1.0 / (1.0 + np.exp(-(float(z @ self.weights) + self.bias))))


def _columns(rows: Sequence[Mapping[str, Any]], modes: Sequence[str]):
    """Feature matrix, labels, and the modes that actually vary in training."""
    import numpy as np

    x = np.array([[row["features"][name] for name in modes] for row in rows], dtype=float)
    y = np.array([bool(row["fallen"]) for row in rows])
    keep = [i for i, name in enumerate(modes) if x[:, i].std() >= MIN_TRAINING_STD]
    dropped = tuple(name for i, name in enumerate(modes) if i not in keep)
    return x, y, keep, dropped


def fit_candidates(rows: Sequence[Mapping[str, Any]],
                   modes: Sequence[str] = FEATURE_NAMES) -> dict[str, Any]:
    """Fit both formulas on `rows` and return them by name."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    x, y, keep, dropped = _columns(rows, modes)
    if not keep:
        raise ValueError("no feature varies enough in training to fit on")

    per_mode = {}
    for i in keep:
        name = modes[i]
        mean, std = float(x[:, i].mean()), float(x[:, i].std())
        z = ((x[:, i] - mean) / std).reshape(-1, 1)
        fit = LogisticRegression(max_iter=1000).fit(z, y)
        per_mode[name] = ModeModel(name, mean, std,
                                   float(fit.coef_[0][0]), float(fit.intercept_[0]))

    kept = x[:, keep]
    mean, std = kept.mean(axis=0), kept.std(axis=0)
    joint = LogisticRegression(max_iter=1000).fit((kept - mean) / std, y)
    return {
        "or": OrModel(per_mode, dropped),
        "sum": SumModel(tuple(modes[i] for i in keep), mean, std,
                        joint.coef_[0], float(joint.intercept_[0]), dropped),
    }


def cross_validate(rows: Sequence[Mapping[str, Any]],
                   modes: Sequence[str] = FEATURE_NAMES) -> dict[str, dict]:
    """Leave-one-episode-out AUC for each candidate.

    Episodes with a single class are skipped: AUC is undefined there, and
    counting them as 0 or 1 would let one recording decide the comparison.
    """
    import numpy as np
    from sklearn.metrics import roc_auc_score

    episodes = sorted({row["episode"] for row in rows})
    per_episode: dict[str, dict[str, float]] = {"or": {}, "sum": {}}
    for episode in episodes:
        held = [r for r in rows if r["episode"] == episode]
        rest = [r for r in rows if r["episode"] != episode]
        y = [bool(r["fallen"]) for r in held]
        if len(set(y)) < 2 or not rest:
            continue
        models = fit_candidates(rest, modes)
        for name, model in models.items():
            per_episode[name][episode] = float(
                roc_auc_score(y, [model.score(r["features"]) for r in held]))

    report = {}
    for name, scores in per_episode.items():
        values = list(scores.values())
        report[name] = {
            "per_episode": scores,
            "mean_auc": float(np.mean(values)) if values else float("nan"),
            "worst_auc": float(np.min(values)) if values else float("nan"),
        }
    return report
