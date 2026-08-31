"""Guard the review tool: it must call the shared augmentation code, produce
one sheet per source frame, and report severity that tracks real strength.

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


def test_sheet_wraps_into_a_grid_of_fixed_width(tmp_path):
    written = preview.render(_frames(tmp_path / "src", 1), tmp_path / "out")
    sheet = cv2.imread(str(written[0]))
    panels = 1 + len(scenarios.GROUPS)
    columns = min(preview.COLUMNS, panels)
    assert sheet.shape[1] == preview.COLUMN_WIDTH * columns


def test_group_mode_shows_every_recipe_in_that_group(tmp_path):
    written = preview.render(_frames(tmp_path / "src", 1), tmp_path / "out", group="S2")
    sheet = cv2.imread(str(written[0]))
    panels = 1 + len(scenarios.recipes_in("S2"))
    # Six panels wrap to two rows of five.
    assert sheet.shape[1] == preview.COLUMN_WIDTH * min(preview.COLUMNS, panels)
    assert panels == 6


def test_uses_the_shared_recipe_code(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(scenarios, "apply_group",
                        lambda image, name: seen.append(name) or image)
    preview.render(_frames(tmp_path / "src", 1), tmp_path / "out")
    assert seen == list(scenarios.GROUPS)


def test_rejects_unknown_group(tmp_path):
    with pytest.raises(ValueError):
        preview.render(_frames(tmp_path / "src", 1), tmp_path / "out", group="S9")


def test_empty_source_directory_is_an_error(tmp_path):
    (tmp_path / "src").mkdir()
    with pytest.raises(ValueError):
        preview.render(tmp_path / "src", tmp_path / "out")


def test_dataset_mode_prefers_a_frame_with_a_fallen_person(tmp_path):
    """Reviewing an empty-floor frame hides what an effect does to the subject."""
    root = tmp_path / "merged"
    (root / "valid/images").mkdir(parents=True)
    for name in ("a.jpg", "b.jpg"):
        cv2.imwrite(str(root / "valid/images" / name),
                    np.zeros((32, 40, 3), dtype=np.uint8))
    (root / "posture_manifest.csv").write_text(
        "image,posture\n"
        "train/images/x.jpg,fallen\n"
        "valid/images/a.jpg,standing\n"
        "valid/images/b.jpg,fallen\n", encoding="utf-8")

    picked = preview.frames_from_dataset(root, limit=1, posture="fallen")
    assert [p.name for p in picked] == ["b.jpg"]


def test_dataset_mode_falls_back_when_no_frame_has_that_posture(tmp_path):
    root = tmp_path / "merged"
    (root / "valid/images").mkdir(parents=True)
    (root / "posture_manifest.csv").write_text(
        "image,posture\nvalid/images/a.jpg,standing\n", encoding="utf-8")
    picked = preview.frames_from_dataset(root, limit=1, posture="fallen")
    assert [p.name for p in picked] == ["a.jpg"]


def test_all_groups_writes_one_sheet_per_group_plus_an_overview(tmp_path):
    """One command must reproduce the whole review set."""
    written = preview.render_all_groups(_frames(tmp_path / "src", 1), tmp_path / "out")
    names = sorted(p.name for p in written)
    assert names == sorted(["00_overview.png"] + [f"{g}.png" for g in scenarios.GROUPS])
    assert all(p.is_file() for p in written)


@pytest.fixture
def frames():
    """Two synthetic RGB frames, enough for the severity maths."""
    rng = np.random.default_rng(0)
    return [rng.integers(0, 255, (64, 80, 3), dtype=np.uint8) for _ in range(2)]


def test_a_heavier_recipe_reports_a_larger_share(frames):
    _, light = preview.measure(frames, "S4_frost_rime")
    _, heavy = preview.measure(frames, "S4_frost_thick")
    assert heavy > light


def test_the_report_covers_every_recipe(frames):
    text = preview.severity_report(frames)
    for recipe in scenarios.RECIPES:
        assert recipe.id in text


def test_the_report_flags_a_recipe_that_barely_changes_the_frame(frames, monkeypatch):
    monkeypatch.setattr(scenarios, "apply_recipe", lambda image, rid: image)
    assert "barely changes the frame" in preview.severity_report(frames)


@pytest.mark.parametrize("name", sorted(preview.SWEEPS))
def test_every_sweep_renders(name, frames, tmp_path):
    target = preview.sweep(frames[0], name, tmp_path)
    assert target.is_file()
    sheet = cv2.imread(str(target))
    assert sheet is not None and sheet.size > 0
