"""The severity report must actually distinguish a strong effect from a weak one.

    pytest vision_ai/tooling/augmentation_preview/tests/test_severity.py
"""

from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from vision_ai.tooling.augmentation_preview import severity
from vision_ai.utils.augmentation import scenarios


@pytest.fixture
def frames():
    rng = np.random.default_rng(0)
    return [rng.integers(0, 255, (64, 80, 3), dtype=np.uint8) for _ in range(2)]


def test_a_heavier_recipe_reports_a_larger_share(frames):
    _, light = severity.measure(frames, "S4_frost_rime")
    _, heavy = severity.measure(frames, "S4_frost_thick")
    assert heavy > light


def test_the_report_covers_every_recipe(frames):
    text = severity.report(frames)
    for recipe in scenarios.RECIPES:
        assert recipe.id in text


def test_the_report_flags_a_recipe_that_barely_changes_the_frame(frames, monkeypatch):
    monkeypatch.setattr(scenarios, "apply_recipe", lambda image, rid: image)
    assert "barely changes the frame" in severity.report(frames)


@pytest.mark.parametrize("name", sorted(severity.SWEEPS))
def test_every_sweep_renders(name, frames, tmp_path):
    target = severity.sweep(frames[0], name, tmp_path)
    assert target.is_file()
    sheet = cv2.imread(str(target))
    assert sheet is not None and sheet.size > 0
