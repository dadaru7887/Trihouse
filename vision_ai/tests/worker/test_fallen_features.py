"""분류기가 학습한 것과 같은 좌표계에서 피처를 잰다.

    pytest vision_ai/tests/worker/test_fallen_features.py

Horizontality, empty masks and diagnostics are covered in
test_fallen_features_v2.py; the upstream five live in test_legacy_features.py.
"""

import numpy as np
import pytest

FRAME = (480, 640)  # (height, width) — deliberately not square


def mask_at(x: int, y: int, width: int, height: int):
    """A filled rectangle on a FRAME-sized bool mask."""
    mask = np.zeros(FRAME, dtype=bool)
    mask[y:y + height, x:x + width] = True
    return mask


def test_aspect_ratio_is_measured_on_normalized_coordinates() -> None:
    """On a 640x480 frame a 200x100 pixel mask is 2.0 in pixels but 1.5 normalized."""
    from vision_ai.models.perception.features import geometric_features

    aspect, _ = geometric_features(mask_at(0, 0, 200, 100), FRAME)

    assert aspect == pytest.approx(1.5, abs=1e-6)
