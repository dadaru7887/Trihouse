"""Load the trained fall classifier: the dev_vision joblib bundle, unchanged.

    classifier = FallenClassifier(bundle_path, approved_sha256)
    classifier.load()
    probability = classifier.probability(features)

The rule in `robot/perception/posture.py` looks at aspect ratio alone and has
a measured recall hole: a body below the tilt threshold never reaches the
suspected state at all, and no amount of temporal logic recovers it. This
classifier is the second signal for exactly that case.

Loading follows the same approval path as every other shipped artifact: the
approval flag and the SHA-256 must both match. A bundle that wants prompt
features this stage cannot compute, or whose feature count or order differs
from the contract, is refused rather than run to produce quiet nonsense.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from pathlib import Path
from typing import Sequence

from vision_ai.models.perception.features import FEATURE_NAMES


class FallenClassifier:
    def __init__(self, bundle_path: Path, bundle_sha256: str, *, approved: bool = True):
        self.bundle_path = Path(bundle_path)
        self.bundle_sha256 = bundle_sha256.lower()
        self.approved = approved
        self._scaler = None
        self._model = None
        self.threshold: float | None = None

    def load(self) -> None:
        if not self.approved:
            raise PermissionError("fallen classifier is not approved for inference")
        digest = hashlib.sha256(self.bundle_path.read_bytes()).hexdigest()
        if digest != self.bundle_sha256:
            raise ValueError("fallen classifier SHA-256 does not match the approved manifest")

        import joblib

        bundle = joblib.load(self.bundle_path)
        config = bundle.get("config", {})
        if config.get("use_prompt_features"):
            raise ValueError(
                "fallen classifier expects prompt features, which this stage does not compute"
            )
        model = bundle["clf"]
        if int(getattr(model, "n_features_in_", 0)) != len(FEATURE_NAMES):
            raise ValueError(
                f"fallen classifier must take exactly the {len(FEATURE_NAMES)} "
                f"contracted features: {', '.join(FEATURE_NAMES)}"
            )
        # Features are passed positionally, so the count matching proves nothing
        # about the order. A bundle trained with aspect_ratio and centroid_y
        # swapped loads clean and inverts the strongest signal.
        names = bundle.get("feature_names")
        if names is not None and tuple(names) != FEATURE_NAMES:
            raise ValueError(
                "fallen classifier bundle has a different feature order: "
                f"expected {FEATURE_NAMES}, bundle has {tuple(names)}"
            )
        self._scaler = bundle["scaler"]
        self._model = model
        # The threshold chosen on valid during training; never overwritten
        # with an arbitrary 0.5.
        self.threshold = float(bundle.get("threshold", 0.5))

    def probability(self, features: Sequence[float]) -> float:
        if self._model is None:
            self.load()
        import numpy as np

        row = np.asarray(features, dtype=np.float64).reshape(1, -1)
        return float(self._model.predict_proba(self._scaler.transform(row))[0, 1])

    def is_fallen(self, features: Sequence[float]) -> bool:
        return self.probability(features) >= self.threshold


def build_classifier_from_env(env: Mapping[str, str]) -> FallenClassifier | None:
    """Build a classifier only when both the bundle and its approved digest are set.

    Neither set means the pre-classifier behaviour: the aspect-ratio rule
    alone. Exactly one set is a deployment mistake rather than an opt-out, so
    it raises instead of silently disabling the classifier.
    """
    path = env.get("FALLEN_CLASSIFIER_BUNDLE")
    digest = env.get("FALLEN_CLASSIFIER_SHA256")
    if not path and not digest:
        return None
    if not path or not digest:
        raise ValueError(
            "FALLEN_CLASSIFIER_BUNDLE and FALLEN_CLASSIFIER_SHA256 must be set together"
        )
    return FallenClassifier(Path(path), digest, approved=True)
