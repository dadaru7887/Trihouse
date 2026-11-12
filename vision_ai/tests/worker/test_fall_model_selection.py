"""The trainer must fit both candidate formulas and let the data pick.

    pytest vision_ai/tests/worker/test_fall_model_selection.py

Which formula wins was measured on ground-truth masks; the deployed model is
fitted on the segmentation model's masks, whose edges differ. So the choice is
re-made from evidence on every run rather than baked in here.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("sklearn")

from vision_ai.models.perception.trainer.fall_model import (
    ModeModel, OrModel, SumModel, cross_validate, fit_candidates,
)


def _rows(n=240, seed=0):
    """Separable instances: upright narrow and upright, fallen wide and tilted."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        fallen = i % 3 != 0
        a = rng.normal(1.30 if fallen else 0.45, 0.08)
        h = rng.normal(0.80 if fallen else 0.10, 0.06)
        rows.append({"features": {"aspect_ratio": float(a), "axis_horizontality": float(h)},
                     "fallen": fallen, "split": "train" if i % 4 else "valid",
                     "episode": f"ep{i % 4}"})
    return rows


def test_it_fits_both_candidates():
    models = fit_candidates(_rows())
    assert set(models) == {"or", "sum"}
    assert isinstance(models["or"], OrModel)
    assert isinstance(models["sum"], SumModel)


def test_the_or_model_holds_one_calibrated_model_per_mode():
    """Each mode is fitted alone, so its probability means something on its own."""
    model = fit_candidates(_rows())["or"]
    assert set(model.modes) == {"aspect_ratio", "axis_horizontality"}
    assert all(isinstance(m, ModeModel) for m in model.modes.values())


def test_the_or_score_is_the_largest_mode_probability():
    """Not an average: whichever posture detector is most confident decides.

    Which rule generalises better is not settled here -- it is re-measured by
    cross_validate on every run, because the answer depends on the masks the
    features were computed from.
    """
    model = fit_candidates(_rows())["or"]
    features = {"aspect_ratio": 1.30, "axis_horizontality": 0.80}
    per_mode = [m.probability(features[name]) for name, m in model.modes.items()]
    assert model.score(features) == pytest.approx(max(per_mode))


def test_the_two_rules_disagree_when_one_mode_is_confident_alone():
    """A fall only one feature can see: max keeps that evidence, the sum
    averages it against the other feature's silence."""
    models = fit_candidates(_rows())
    only_tilted = {"aspect_ratio": 0.45, "axis_horizontality": 0.80}
    assert models["or"].score(only_tilted) > models["sum"].score(only_tilted)


def test_cross_validation_holds_out_whole_episodes():
    report = cross_validate(_rows())
    assert set(report) == {"or", "sum"}
    assert len(report["or"]["per_episode"]) == 4
    assert 0.0 <= report["or"]["mean_auc"] <= 1.0
    assert report["or"]["worst_auc"] <= report["or"]["mean_auc"]


def test_a_mode_that_saw_no_variation_is_dropped_not_scaled():
    """contact_person_iou was zero in 97% of training rows: StandardScaler then
    divides by a near-zero variance and a small value at inference explodes to
    18.8 standardised, dragging the whole score down.
    """
    rows = _rows()
    for row in rows:
        row["features"]["contact_person_iou"] = 0.0
    model = fit_candidates(rows, modes=("aspect_ratio", "axis_horizontality",
                                        "contact_person_iou"))["or"]
    assert "contact_person_iou" not in model.modes
    assert model.dropped == ("contact_person_iou",)


def test_the_score_is_reported_in_original_feature_units():
    """A coefficient means nothing without the scaler; the crossing point does."""
    model = fit_candidates(_rows())["or"]
    crossings = model.crossing_points()
    assert set(crossings) == {"aspect_ratio", "axis_horizontality"}
    assert 0.3 < crossings["aspect_ratio"] < 1.5
