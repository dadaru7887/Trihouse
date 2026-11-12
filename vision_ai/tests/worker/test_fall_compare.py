"""The A/B/C fall-feature comparison: same people, same split, test opened once.

    pytest vision_ai/tests/worker/test_fall_compare.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
pytest.importorskip("sklearn")

from vision_ai.data_loader.fall.compare_rows import (
    GROUPS, _match, build_rows, check_sessions, parse_label,
)
from vision_ai.models.perception.trainer.fall_compare import (
    _floor_threshold, evaluate, run,
)

NAMES = ["Fallen", "Obstacle", "Standing"]


def _poly(cls: int, x0, y0, x1, y1) -> str:
    """One YOLO-seg label line for a rectangle."""
    return f"{cls} {x0} {y0} {x1} {y0} {x1} {y1} {x0} {y1}\n"


def _export(root: Path, frames: dict[str, list[tuple[str, str]]]) -> Path:
    """Roboflow-shaped export with names Fallen/Obstacle/Standing."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "data.yaml").write_text("names:\n- Fallen\n- Obstacle\n- Standing\nnc: 3\n",
                                    encoding="utf-8")
    for split, entries in frames.items():
        (root / split / "images").mkdir(parents=True, exist_ok=True)
        (root / split / "labels").mkdir(parents=True, exist_ok=True)
        for name, label in entries:
            cv2.imwrite(str(root / split / "images" / f"{name}.jpg"),
                        np.zeros((48, 64, 3), np.uint8))
            (root / split / "labels" / f"{name}.txt").write_text(label, encoding="utf-8")
    return root


def _frame(stamp: str, t: int) -> str:
    return f"dataset_video_20260822_{stamp}_t{t:04d}-00s_jpg.rf.h{t}"


def _people(rng, fallen: bool) -> str:
    """A lying or standing person with jitter, sometimes with an obstacle."""
    if fallen:
        w, h = rng.uniform(0.35, 0.6), rng.uniform(0.08, 0.2)
        line = _poly(0, 0.2, 0.5, 0.2 + w, 0.5 + h)
    else:
        w, h = rng.uniform(0.06, 0.15), rng.uniform(0.35, 0.6)
        line = _poly(2, 0.5, 0.2, 0.5 + w, 0.2 + h)
    if rng.random() < 0.3:
        line += _poly(1, 0.02, 0.02, 0.1, 0.1)
    return line


def _dataset(tmp_path: Path) -> Path:
    rng = np.random.default_rng(0)
    frames = {}
    for split, stamps in (("train", ("100000", "110000")), ("valid", ("200000",)),
                          ("test", ("300000",))):
        frames[split] = [(_frame(s, t), _people(rng, t % 2 == 0))
                         for s in stamps for t in range(16)]
    return _export(tmp_path / "fallen", frames)


def test_a_malformed_line_drops_the_whole_image():
    """A missing neighbour must not become a contact IoU of 0."""
    assert parse_label("2 0.1 0.1 0.2 0.1 0.2 0.3\n1 0.5 0.5\n", NAMES) is None
    assert len(parse_label(_poly(2, 0.1, 0.1, 0.2, 0.3), NAMES)) == 1


def test_every_group_is_measured_on_the_same_people(tmp_path):
    rows, _, report = build_rows(_dataset(tmp_path), masks="gt")

    names = {n for group in GROUPS.values() for n in group}
    assert rows and all(set(r["features"]) == names for r in rows)
    assert report["sessions"]["test"] == ["20260822_300000"]


def test_malformed_images_are_reported_not_zero_filled(tmp_path):
    export = _dataset(tmp_path)
    bad = sorted((export / "train" / "labels").iterdir())[0]
    bad.write_text(bad.read_text(encoding="utf-8") + "1 0.5 0.5\n", encoding="utf-8")

    rows, _, report = build_rows(export, masks="gt")

    assert report["skipped"]["malformed_label_image"] == 1
    assert not any(r["image"].endswith(bad.stem + ".jpg") for r in rows)


def test_a_session_in_two_splits_is_refused(tmp_path):
    export = _export(tmp_path / "x", {
        "train": [(_frame("100000", 0), _poly(2, 0.1, 0.1, 0.2, 0.5))],
        "test": [(_frame("100000", 1), _poly(2, 0.1, 0.1, 0.2, 0.5))]})

    with pytest.raises(ValueError, match="20260822_100000"):
        check_sessions(export, None)


def test_a_merge_that_disagrees_with_the_export_split_is_refused(tmp_path):
    export = _dataset(tmp_path)
    merged = tmp_path / "merged"
    for split in ("train", "valid", "test"):
        (merged / split / "images").mkdir(parents=True)
        for image in (export / split / "images").iterdir():
            # Put everything in train: the detector would have seen valid/test.
            (merged / "train" / "images" / image.name).touch()

    with pytest.raises(ValueError, match="different split"):
        check_sessions(export, merged)


def test_the_floor_threshold_is_the_most_precise_one_meeting_recall():
    labels = [1, 1, 1, 1, 0, 0, 0, 0]
    scores = [0.9, 0.8, 0.7, 0.2, 0.6, 0.3, 0.1, 0.05]

    threshold, scored, met = _floor_threshold(labels, scores, 0.75)

    assert met and threshold == 0.7          # 3/4 recall, no false positive
    assert scored["precision"] == 1.0


def test_a_missed_detection_is_a_missed_fall_end_to_end():
    models = {"A": {"threshold_recall_floor": 0.5, "threshold_f1": 0.5}}
    rows = [
        {"split": "test", "fallen": True, "features": {"x": 1}, "scores": {"A": 0.9}},
        {"split": "test", "fallen": True, "features": None, "detected": False},
        {"split": "test", "fallen": False, "features": {"x": 1}, "scores": {"A": 0.1}},
    ]

    result = evaluate(rows, models)["A"]["threshold_recall_floor"]

    assert result["classifier"]["recall"] == 1.0
    assert result["end_to_end"]["recall"] == 0.5
    assert result["end_to_end"]["false_negative"] == 1


def test_predicted_people_are_matched_one_to_one():
    truth = [np.zeros((10, 10), bool), np.zeros((10, 10), bool)]
    truth[0][0:5, 0:5] = True
    truth[1][0:5, 1:6] = True
    pred = [truth[0].copy()]

    matches = _match(truth, pred)

    assert list(matches) == [0]               # the better overlap wins, once


def test_test_labels_never_reach_fitting_or_thresholds(tmp_path):
    export = _dataset(tmp_path)
    clean = run(export, tmp_path / "clean")
    for label in (export / "test" / "labels").iterdir():
        # Flip Fallen <-> Standing on test only.
        text = label.read_text(encoding="utf-8")
        flipped = "".join(("2" + line[1:] if line[0] == "0" else
                           "0" + line[1:] if line[0] == "2" else line)
                          for line in text.splitlines(keepends=True))
        label.write_text(flipped, encoding="utf-8")
    poisoned = run(export, tmp_path / "poisoned")

    for group in GROUPS:
        for key in ("threshold_recall_floor", "threshold_f1", "weights"):
            assert poisoned["models"][group][key] == clean["models"][group][key]
    assert poisoned["test"]["C"]["threshold_f1"]["classifier"] != \
        clean["test"]["C"]["threshold_f1"]["classifier"]
    assert json.loads((tmp_path / "clean" / "report.json").read_text())["masks"] == "gt"
    assert (tmp_path / "clean" / "report.md").is_file()
