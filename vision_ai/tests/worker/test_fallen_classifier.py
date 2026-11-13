"""학습된 낙상 분류기를 운영 계약 안에서 싣는다.

    pytest vision_ai/tests/worker/test_fallen_classifier.py

Bundles are built the way fall_trainer.py writes them:
{"model", "kind", "feature_names", "threshold"}.
"""

import hashlib
from pathlib import Path

import pytest

joblib = pytest.importorskip("joblib")
pytest.importorskip("sklearn")

# The upstream five-feature bundle, mirrored from origin/dev_vision.
UPSTREAM_BUNDLE = Path(
    "vision_ai/upstream/dev_vision/classifier"
    "/fallen_classifier_contact_seed42.joblib"
)
LYING = {"aspect_ratio": 1.4, "axis_horizontality": 0.9}
STANDING = {"aspect_ratio": 0.4, "axis_horizontality": 0.1}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows():
    """Separable training rows on the contract features."""
    rows = []
    for i in range(24):
        fallen = i % 2 == 0
        base = LYING if fallen else STANDING
        rows.append({"features": {k: v + 0.01 * i for k, v in base.items()},
                     "fallen": fallen, "split": "train", "episode": f"ep{i % 3}"})
    return rows


def _write_bundle(tmp_path, kind="sum", **overrides):
    """Fit both formulas, keep `kind`, and dump a trainer-shaped bundle."""
    from vision_ai.models.perception.features import FEATURE_NAMES
    from vision_ai.models.perception.trainer.fall_model import fit_candidates

    bundle = {"model": fit_candidates(_rows())[kind], "kind": kind,
              "feature_names": list(FEATURE_NAMES), "threshold": 0.5}
    bundle.update(overrides)
    path = tmp_path / "classifier.joblib"
    joblib.dump(bundle, path)
    return path, _digest(path)


def test_the_classifier_uses_the_threshold_chosen_during_training(tmp_path) -> None:
    """Not 0.5 by convention: the bundle carries the value chosen on valid."""
    from vision_ai.models.perception.fall_classifier import FallenClassifier

    path, digest = _write_bundle(tmp_path, threshold=0.73)
    classifier = FallenClassifier(path, digest, approved=True)
    classifier.load()

    assert classifier.threshold == 0.73


@pytest.mark.parametrize("kind", ["or", "sum"])
def test_a_lying_shape_scores_higher_than_a_standing_one(tmp_path, kind) -> None:
    from vision_ai.models.perception.fall_classifier import FallenClassifier

    path, digest = _write_bundle(tmp_path, kind=kind)
    classifier = FallenClassifier(path, digest, approved=True)

    assert classifier.probability(LYING) > classifier.probability(STANDING)
    assert classifier.is_fallen(LYING)
    assert not classifier.is_fallen(STANDING)
    assert classifier.kind == kind


def test_the_window_decides_on_the_median_against_the_bundle_threshold(tmp_path) -> None:
    from vision_ai.models.perception.fall_classifier import FallenClassifier

    path, digest = _write_bundle(tmp_path, threshold=0.5)
    classifier = FallenClassifier(path, digest, approved=True)
    classifier.load()

    assert classifier.is_fallen_window([0.9, 0.1, 0.8]) is True     # median 0.8
    assert classifier.is_fallen_window([0.9, 0.1, 0.2]) is False    # median 0.2
    assert classifier.is_fallen_window([]) is None


def test_an_unapproved_classifier_is_refused(tmp_path) -> None:
    from vision_ai.models.perception.fall_classifier import FallenClassifier

    path, digest = _write_bundle(tmp_path)

    with pytest.raises(PermissionError):
        FallenClassifier(path, digest, approved=False).load()


def test_a_classifier_whose_checksum_does_not_match_is_refused(tmp_path) -> None:
    from vision_ai.models.perception.fall_classifier import FallenClassifier

    path, _ = _write_bundle(tmp_path)

    with pytest.raises(ValueError, match="SHA-256"):
        FallenClassifier(path, "0" * 64, approved=True).load()


def test_a_bundle_whose_feature_order_differs_is_refused(tmp_path) -> None:
    """A reordered bundle loads clean and scores the wrong quantity unless refused."""
    from vision_ai.models.perception.features import FEATURE_NAMES
    from vision_ai.models.perception.fall_classifier import FallenClassifier

    path, digest = _write_bundle(tmp_path, feature_names=list(reversed(FEATURE_NAMES)))

    with pytest.raises(ValueError, match="different features"):
        FallenClassifier(path, digest).load()


def test_the_upstream_five_feature_bundle_is_refused() -> None:
    """The dev_vision bundle was fitted on five features the contract dropped."""
    from vision_ai.models.perception.fall_classifier import FallenClassifier

    import numpy

    if not UPSTREAM_BUNDLE.exists():
        pytest.skip("upstream fallen-detection mirror is not checked out")
    if int(numpy.__version__.split(".")[0]) < 2:
        pytest.skip("the upstream bundle was pickled under numpy 2")
    with pytest.raises(ValueError, match="different features"):
        FallenClassifier(UPSTREAM_BUNDLE, _digest(UPSTREAM_BUNDLE)).load()


def test_scoring_without_a_contract_feature_is_refused(tmp_path) -> None:
    from vision_ai.models.perception.fall_classifier import FallenClassifier

    path, digest = _write_bundle(tmp_path)

    with pytest.raises(ValueError, match="missing features"):
        FallenClassifier(path, digest).probability({"aspect_ratio": 1.0})


def test_absent_classifier_environment_keeps_the_aspect_ratio_rule() -> None:
    from vision_ai.models.perception.fall_classifier import build_classifier_from_env

    assert build_classifier_from_env({}) is None


def test_classifier_environment_binds_the_bundle_to_its_checksum() -> None:
    """Names match compose.ai_5080.yaml and .env.example."""
    from vision_ai.models.perception.fall_classifier import build_classifier_from_env

    classifier = build_classifier_from_env({
        "FALLEN_CLASSIFIER_BUNDLE": "/models/fallen.joblib",
        "FALLEN_CLASSIFIER_SHA256": "A" * 64,
    })

    assert classifier is not None
    assert classifier.bundle_path == Path("/models/fallen.joblib")
    assert classifier.bundle_sha256 == "a" * 64


@pytest.mark.parametrize("env", [
    {"FALLEN_CLASSIFIER_BUNDLE": "/models/fallen.joblib"},
    {"FALLEN_CLASSIFIER_SHA256": "a" * 64},
])
def test_a_half_configured_classifier_fails_loudly(env) -> None:
    from vision_ai.models.perception.fall_classifier import build_classifier_from_env

    with pytest.raises(ValueError, match="FALLEN_CLASSIFIER"):
        build_classifier_from_env(env)
