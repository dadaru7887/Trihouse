"""Guard the preview tool: it must call the shared augmentation code and
produce one sheet per source frame.

    pytest vision_ai/tooling/augmentation_preview
"""

from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from vision_ai.tooling.augmentation_preview import preview
from vision_ai.utils.augmentation import scenarios


def _frames(directory, count=2):
    """Write `count` deterministic BGR frames and return the directory."""
    directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0)
    for index in range(count):
        cv2.imwrite(str(directory / f"frame_{index}.jpg"),
                    rng.integers(0, 255, (48, 64, 3), dtype=np.uint8))
    return directory


def test_renders_one_sheet_per_frame(tmp_path):
    written = preview.render(_frames(tmp_path / "src"), tmp_path / "out", limit=2)
    assert len(written) == 2
    assert all(path.is_file() for path in written)


def test_sheet_has_one_panel_per_scenario_plus_original(tmp_path):
    written = preview.render(_frames(tmp_path / "src", 1), tmp_path / "out")
    sheet = cv2.imread(str(written[0]))
    # Panels are tiled horizontally at a fixed width: original + S1..S5.
    assert sheet.shape[1] == preview.COLUMN_WIDTH * (1 + len(scenarios.SCENARIOS))


def test_single_scenario_mode_repeats_that_scenario(tmp_path):
    written = preview.render(_frames(tmp_path / "src", 1), tmp_path / "out",
                             scenario="S2", repeats=3)
    sheet = cv2.imread(str(written[0]))
    assert sheet.shape[1] == preview.COLUMN_WIDTH * 4       # original + 3 draws


def test_uses_the_shared_scenario_code(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(scenarios, "apply_scenario",
                        lambda image, name: seen.append(name) or image)
    preview.render(_frames(tmp_path / "src", 1), tmp_path / "out")
    assert seen == list(scenarios.SCENARIOS)


def test_rejects_unknown_scenario(tmp_path):
    with pytest.raises(ValueError):
        preview.render(_frames(tmp_path / "src", 1), tmp_path / "out", scenario="S9")


def test_empty_source_directory_is_an_error(tmp_path):
    (tmp_path / "src").mkdir()
    with pytest.raises(ValueError):
        preview.render(tmp_path / "src", tmp_path / "out")
