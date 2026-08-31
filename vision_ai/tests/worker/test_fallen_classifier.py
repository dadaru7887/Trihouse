"""학습된 낙상 분류기를 운영 계약 안에서 싣는다."""

import hashlib
from pathlib import Path

import numpy as np
import pytest

joblib = pytest.importorskip("joblib")
pytest.importorskip("sklearn")

BUNDLE = Path(
    "vision_ai/upstream/dev_vision/classifier"
    "/fallen_classifier_contact_seed42.joblib"
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_bundle(tmp_path, **overrides):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    features = np.array([[0.3, 90.0, 0.3, 0.0, 0.0]] * 6 + [[3.0, 5.0, 0.8, 0.1, 0.0]] * 6)
    labels = np.array([0] * 6 + [1] * 6)
    scaler = StandardScaler().fit(features)
    bundle = {
        "scaler": scaler,
        "clf": LogisticRegression().fit(scaler.transform(features), labels),
        "threshold": 0.5,
        "config": {"use_geometric_features": True, "use_prompt_features": False,
                   "use_contact_features": True},
    }
    bundle.update(overrides)
    path = tmp_path / "classifier.joblib"
    joblib.dump(bundle, path)
    return path, _digest(path)


def test_the_classifier_uses_the_threshold_chosen_during_training(tmp_path) -> None:
    """Not 0.5 by convention: the bundle carries the k-fold selected value."""
    from vision_ai.models.perception.fall_classifier import FallenClassifier

    path, digest = _write_bundle(tmp_path, threshold=0.73)
    classifier = FallenClassifier(path, digest, approved=True)
    classifier.load()

    assert classifier.threshold == 0.73


def test_a_lying_shape_scores_higher_than_a_standing_one(tmp_path) -> None:
    from vision_ai.models.perception.fall_classifier import FallenClassifier

    path, digest = _write_bundle(tmp_path)
    classifier = FallenClassifier(path, digest, approved=True)

    lying = classifier.probability((3.0, 5.0, 0.8, 0.1, 0.0))
    standing = classifier.probability((0.3, 90.0, 0.3, 0.0, 0.0))

    assert lying > standing
    assert classifier.is_fallen((3.0, 5.0, 0.8, 0.1, 0.0))
    assert not classifier.is_fallen((0.3, 90.0, 0.3, 0.0, 0.0))


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


def test_a_bundle_expecting_prompt_features_is_refused(tmp_path) -> None:
    """Prompt features need a VLM pass this stage does not run."""
    from vision_ai.models.perception.fall_classifier import FallenClassifier

    path, digest = _write_bundle(tmp_path, config={
        "use_geometric_features": True, "use_prompt_features": True,
        "use_contact_features": True,
    })

    with pytest.raises(ValueError, match="prompt"):
        FallenClassifier(path, digest, approved=True).load()


def test_a_bundle_with_the_wrong_feature_count_is_refused(tmp_path) -> None:
    from vision_ai.models.perception.fall_classifier import FallenClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    features = np.array([[0.3, 90.0]] * 6 + [[3.0, 5.0]] * 6)
    labels = np.array([0] * 6 + [1] * 6)
    scaler = StandardScaler().fit(features)
    path, digest = _write_bundle(
        tmp_path, scaler=scaler,
        clf=LogisticRegression().fit(scaler.transform(features), labels),
    )

    with pytest.raises(ValueError, match="contracted features"):
        FallenClassifier(path, digest, approved=True).load()


def test_the_shipped_dev_vision_classifier_loads_and_scores() -> None:
    from vision_ai.models.perception.fall_classifier import FallenClassifier

    if not BUNDLE.exists():
        pytest.skip("upstream fallen-detection mirror is not checked out")
    classifier = FallenClassifier(BUNDLE, _digest(BUNDLE), approved=True)

    lying = classifier.probability((3.0, 5.0, 0.8, 0.0, 0.0))
    standing = classifier.probability((0.3, 90.0, 0.3, 0.0, 0.0))

    assert 0.0 <= standing < lying <= 1.0
    assert classifier.threshold == pytest.approx(0.5, abs=1e-9)


def test_absent_classifier_environment_keeps_the_aspect_ratio_rule() -> None:
    from vision_ai.models.perception.fall_classifier import build_classifier_from_env

    assert build_classifier_from_env({}) is None


def test_classifier_environment_binds_the_bundle_to_its_checksum() -> None:
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


def test_a_bundle_whose_feature_order_differs_is_refused(tmp_path):
    """The count alone cannot catch a reordering, and five wrong-order values
    load clean and produce silently wrong probabilities.

    aspect_ratio carries the largest coefficient in the delivered bundle, so
    swapping it with centroid_y flips the strongest signal with no error.
    """
    import joblib
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    from vision_ai.models.perception.features import FEATURE_NAMES
    from vision_ai.models.perception.fall_classifier import FallenClassifier

    rows = np.random.default_rng(0).random((20, len(FEATURE_NAMES)))
    labels = (rows[:, 0] > 0.5).astype(int)
    scaler = StandardScaler().fit(rows)
    model = LogisticRegression().fit(scaler.transform(rows), labels)

    shuffled = list(FEATURE_NAMES)
    shuffled[0], shuffled[2] = shuffled[2], shuffled[0]
    bundle = tmp_path / "bundle.joblib"
    joblib.dump({"clf": model, "scaler": scaler, "threshold": 0.5,
                 "feature_names": shuffled, "config": {}}, bundle)
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="feature order"):
        FallenClassifier(bundle, digest).load()


def test_a_bundle_with_the_contracted_order_loads(tmp_path):
    import joblib
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    from vision_ai.models.perception.features import FEATURE_NAMES
    from vision_ai.models.perception.fall_classifier import FallenClassifier

    rows = np.random.default_rng(0).random((20, len(FEATURE_NAMES)))
    labels = (rows[:, 0] > 0.5).astype(int)
    scaler = StandardScaler().fit(rows)
    model = LogisticRegression().fit(scaler.transform(rows), labels)

    bundle = tmp_path / "bundle.joblib"
    joblib.dump({"clf": model, "scaler": scaler, "threshold": 0.4,
                 "feature_names": list(FEATURE_NAMES), "config": {}}, bundle)
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()

    classifier = FallenClassifier(bundle, digest)
    classifier.load()
    assert classifier.threshold == 0.4
