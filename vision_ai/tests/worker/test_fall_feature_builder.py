"""Build the fall-classifier feature JSONL from the Roboflow export.

    pytest vision_ai/tests/worker/test_fall_feature_builder.py

The two things that make this dataset wrong rather than merely small: taking
the split from anywhere but the segmentation run (a frame the detector trained
on would score the classifier), and losing which instance was the fallen one
(the merged labels collapse Fallen and Standing into person).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from vision_ai.data_loader.fall.build_features import (
    build_features, instances_from_label, split_index,
)
from vision_ai.models.perception.features import FEATURE_NAMES


def _export(root: Path, rows: dict[str, list[tuple[str, str]]]):
    """Write a Roboflow-shaped export: names Fallen/Obstacle/Standing."""
    (root).mkdir(parents=True, exist_ok=True)
    (root / "data.yaml").write_text(
        "names:\n- Fallen\n- Obstacle\n- Standing\nnc: 3\n", encoding="utf-8")
    for split, entries in rows.items():
        (root / split / "images").mkdir(parents=True, exist_ok=True)
        (root / split / "labels").mkdir(parents=True, exist_ok=True)
        for name, label in entries:
            cv2.imwrite(str(root / split / "images" / f"{name}.jpg"),
                        np.zeros((40, 60, 3), dtype=np.uint8))
            (root / split / "labels" / f"{name}.txt").write_text(label, encoding="utf-8")


def _merged(root: Path, placement: dict[str, list[str]]):
    """Write just enough of a merged dataset to carry the split assignment."""
    for split, names in placement.items():
        (root / split / "images").mkdir(parents=True, exist_ok=True)
        for name in names:
            (root / split / "images" / f"{name}.jpg").touch()


# A person standing upright: tall and narrow. One fallen: wide and flat.
UPRIGHT = "2 0.45 0.20 0.55 0.20 0.55 0.80 0.45 0.80\n"
FALLEN = "0 0.20 0.55 0.80 0.55 0.80 0.65 0.20 0.65\n"
OBSTACLE = "1 0.05 0.05 0.15 0.05 0.15 0.15 0.05 0.15\n"


def test_instances_carry_the_posture_the_merged_labels_dropped(tmp_path):
    """merged/ collapses Fallen and Standing into person; the export still has both."""
    names = ["Fallen", "Obstacle", "Standing"]
    instances = instances_from_label(FALLEN + UPRIGHT + OBSTACLE, names, (40, 60))
    assert [i.class_name for i in instances] == ["Fallen", "Standing", "Obstacle"]
    assert [i.fallen for i in instances] == [True, False, None]


def test_the_split_comes_from_the_merged_dataset(tmp_path):
    """Any other split would put detector-training frames in the classifier's test."""
    merged = tmp_path / "merged"
    _merged(merged, {"train": ["a"], "valid": ["b"], "test": ["c"]})
    index = split_index(merged)
    assert index == {"a.jpg": "train", "b.jpg": "valid", "c.jpg": "test"}


def test_it_writes_one_row_per_person_with_the_contracted_features(tmp_path):
    export = tmp_path / "fallen"
    _export(export, {"train": [("a", FALLEN + UPRIGHT + OBSTACLE)]})
    merged = tmp_path / "merged"
    _merged(merged, {"train": ["a"], "valid": [], "test": []})

    out = tmp_path / "features.jsonl"
    report = build_features(export, merged, out)

    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2                       # the obstacle is context, not a row
    assert {row["fallen"] for row in rows} == {True, False}
    # Named rather than positional, so a reordering cannot go unnoticed.
    assert all(set(row["features"]) >= set(FEATURE_NAMES) for row in rows)
    assert all(row["split"] == "train" for row in rows)
    assert report["rows"] == 2


def test_the_fallen_person_is_wider_than_the_upright_one(tmp_path):
    """aspect_ratio is the strongest feature; a builder that broke it is useless."""
    export = tmp_path / "fallen"
    _export(export, {"train": [("a", FALLEN + UPRIGHT)]})
    merged = tmp_path / "merged"
    _merged(merged, {"train": ["a"], "valid": [], "test": []})

    out = tmp_path / "features.jsonl"
    build_features(export, merged, out)
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    by_label = {row["fallen"]: row["features"]["aspect_ratio"] for row in rows}
    assert by_label[True] > by_label[False]


def test_frames_the_merged_dataset_does_not_hold_are_skipped(tmp_path):
    """A frame outside the split map has no split, and guessing one would leak."""
    export = tmp_path / "fallen"
    _export(export, {"train": [("a", FALLEN), ("stray", FALLEN)]})
    merged = tmp_path / "merged"
    _merged(merged, {"train": ["a"], "valid": [], "test": []})

    out = tmp_path / "features.jsonl"
    report = build_features(export, merged, out)
    assert report["rows"] == 1
    assert report["skipped_not_in_split"] == 1


def test_every_row_carries_the_episode_it_came_from(tmp_path):
    """Cross-validation holds out whole recordings: adjacent frames of one are
    near identical, so a frame-level split would measure memorisation."""
    export = tmp_path / "fallen"
    _export(export, {"train": [("dataset_video_20260822_162137_t0004-00s", FALLEN)]})
    merged = tmp_path / "merged"
    _merged(merged, {"train": ["dataset_video_20260822_162137_t0004-00s"], "valid": [], "test": []})

    out = tmp_path / "features.jsonl"
    build_features(export, merged, out)
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["episode"] == "20260822_162137"


def test_an_empty_result_is_refused(tmp_path):
    """Writing an empty JSONL would fail later, inside the trainer, with no clue why."""
    export = tmp_path / "fallen"
    _export(export, {"train": [("a", OBSTACLE)]})
    merged = tmp_path / "merged"
    _merged(merged, {"train": ["a"], "valid": [], "test": []})

    with pytest.raises(ValueError, match="no person instances"):
        build_features(export, merged, tmp_path / "features.jsonl")
