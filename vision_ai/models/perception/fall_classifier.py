"""Load the trained fall classifier and score one person from their mask.

    classifier = FallenClassifier(bundle_path, approved_sha256)
    classifier.load()
    evidence = classifier.probability({"aspect_ratio": 1.2, "axis_horizontality": 0.8})
    fallen = classifier.is_fallen_window(recent_evidence)

The rule in `robot/perception/posture.py` looks at aspect ratio alone and has a
measured recall hole: a body below the tilt threshold never reaches the
suspected state at all, and no amount of temporal logic recovers it. This
classifier is the second signal for exactly that case.

Loading follows the same approval path as every other shipped artifact: the
approval flag and the SHA-256 must both match. A bundle whose feature names
differ from the contract is refused rather than run -- features are read by
name here, but a bundle fitted on different ones would score a different
quantity with no error.

Deciding is two steps, on two timescales. `probability` scores one frame;
`is_fallen_window` takes the median of the recent frames, so a single dropped
or broken mask cannot decide and a pose held only briefly cannot either. How
long a fall must persist before it is an emergency is not decided here: that
stays in the robot's fall state machine.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping, Sequence

from vision_ai.models.perception.features import FEATURE_NAMES, window_score


class FallenClassifier:
    def __init__(self, bundle_path: Path, bundle_sha256: str, *, approved: bool = True):
        self.bundle_path = Path(bundle_path)
        self.bundle_sha256 = bundle_sha256.lower()
        self.approved = approved
        self._model = None
        self.threshold: float | None = None
        self.kind: str | None = None

    def load(self) -> None:
        """Read the bundle, after checking it is the approved one and fits the contract."""
        import joblib

        if not self.approved:
            raise PermissionError("fallen classifier is not approved for inference")
        digest = hashlib.sha256(self.bundle_path.read_bytes()).hexdigest()
        if digest != self.bundle_sha256:
            raise ValueError("fallen classifier SHA-256 does not match the approved manifest")

        bundle = joblib.load(self.bundle_path)
        names = tuple(bundle.get("feature_names", ()))
        if names != FEATURE_NAMES:
            raise ValueError(
                "fallen classifier bundle was fitted on different features: "
                f"expected {FEATURE_NAMES}, bundle has {names}"
            )
        self._model = bundle["model"]
        self.kind = str(bundle.get("kind", "or"))
        # The threshold chosen on valid during training; never overwritten
        # with an arbitrary 0.5.
        self.threshold = float(bundle["threshold"])

    def probability(self, features: Mapping[str, float]) -> float:
        """Evidence that this one frame shows a fallen person."""
        if self._model is None:
            self.load()
        missing = set(FEATURE_NAMES) - set(features)
        if missing:
            raise ValueError(f"missing features: {sorted(missing)}")
        return float(self._model.score(features))

    def is_fallen(self, features: Mapping[str, float]) -> bool:
        """Decide from one frame. Prefer `is_fallen_window` where history exists."""
        return self.probability(features) >= float(self.threshold)

    def is_fallen_window(self, evidence: Sequence[float]) -> bool | None:
        """Decide from the recent frames' evidence, or `None` with no history."""
        score = window_score(evidence)
        return None if score is None else score >= float(self.threshold)


def build_classifier_from_env(env: Mapping[str, str]) -> FallenClassifier | None:
    """Build a classifier only when both the bundle and its approved digest are set.

    Neither set means the pre-classifier behaviour: the aspect-ratio rule
    alone. Exactly one set is a deployment mistake rather than an opt-out, so
    it raises instead of silently disabling the classifier.
    """
    # Names match compose.ai_5080.yaml and .env.example.
    path = env.get("FALLEN_CLASSIFIER_BUNDLE", "").strip()
    digest = env.get("FALLEN_CLASSIFIER_SHA256", "").strip()
    if not path and not digest:
        return None
    if not path or not digest:
        raise ValueError(
            "set both FALLEN_CLASSIFIER_BUNDLE and FALLEN_CLASSIFIER_SHA256, or neither"
        )
    return FallenClassifier(Path(path), digest, approved=True)
