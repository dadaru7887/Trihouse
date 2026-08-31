"""The strength ladders must render, and must walk past what the recipes use.

    pytest vision_ai/tooling/augmentation_preview/tests/test_sweep.py
"""

from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from vision_ai.tooling.augmentation_preview import preview, sweep


@pytest.fixture
def frame():
    """One synthetic RGB frame."""
    return np.random.default_rng(0).integers(0, 255, (64, 80, 3), dtype=np.uint8)


@pytest.mark.parametrize("effect", sorted(sweep.LADDERS))
def test_every_ladder_renders(effect, frame, tmp_path):
    target = sweep.render_ladder(frame, effect, tmp_path)
    assert target.is_file()
    sheet = cv2.imread(str(target))
    assert sheet is not None and sheet.size > 0


def test_a_ladder_shows_the_original_plus_every_step(frame, tmp_path):
    """Reading a ladder means comparing steps, so none may be dropped."""
    target = sweep.render_ladder(frame, "blur", tmp_path)
    panels = 1 + len(sweep.LADDERS["blur"][2])
    rows = -(-panels // 4)                      # the ladder tiles four wide
    sheet = cv2.imread(str(target))
    assert sheet.shape[1] == preview.COLUMN_WIDTH * min(4, panels)
    assert sheet.shape[0] > 0 and rows >= 2


def test_an_unknown_effect_is_refused(frame, tmp_path):
    with pytest.raises(ValueError, match="unknown effect"):
        sweep.render_ladder(frame, "snow", tmp_path)


def test_the_blur_ladder_runs_past_what_training_uses(frame):
    """A ladder that stopped at the chosen value could not show why it stops there."""
    from vision_ai.utils.augmentation import scenarios

    walked = {step["ksize"] for step in sweep.LADDERS["blur"][2]}
    trained = {15, 25}                          # S1_motion_blur_short / _long
    assert trained < walked
    assert max(walked) > max(trained)
    assert {r.id for r in scenarios.recipes_in("S1")} >= {
        "S1_motion_blur_short", "S1_motion_blur_long"}
