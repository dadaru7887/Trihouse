"""학습된 낙상 분류기. `dev_vision` 배달본의 joblib 번들을 그대로 싣는다.

`posture.py` 의 규칙은 종횡비 하나만 본다. 그 규칙에는 실측된 recall 구멍이
있다 — 기울기가 임계값 밑이면 애초에 의심 단계에 들어가지도 못하고, 그 구멍은
시간축 로직으로 못 메운다(`posture.py` 문서 참고). 이 분류기가 그 2차 신호다.

싣는 절차는 저장소의 다른 승인 산출물과 같다. 승인 플래그와 SHA-256 이 맞아야
하고, 번들이 이 단계가 만들 수 없는 피처(프롬프트)를 요구하거나 피처 개수가
계약과 다르면 조용히 이상한 값으로 도는 대신 거절한다.
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
        # 학습 때 k-fold 로 고른 값을 쓴다. 0.5 같은 임의값으로 덮어쓰지 않는다.
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
    """번들과 승인된 digest 가 **둘 다** 있을 때만 만든다.

    둘 다 비우면 분류기 도입 전 동작, 즉 종횡비 규칙만 쓴다. 하나만 채우는 것은
    배포 실수이지 opt-out 이 아니므로 조용히 끄지 않고 예외를 낸다.
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
