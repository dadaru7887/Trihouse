"""Read the fall-classifier dataset, and refuse it before training if it cannot score.

    from vision_ai.data_loader.fall.dataset import load_dataset
    splits = load_dataset(path)     # {"train": [...], "valid": [...], "test": [...]}

The counterpart of `data_loader/perception/audit.py` on the segmentation side:
passing the format check is not enough. A split with no fallen examples, or no
upright ones, cannot produce a metric, so training stops rather than building
a model whose numbers mean nothing.

One instance per JSONL line, split being one of train, valid or test:

    {"features": [aspect_ratio, pca_angle, centroid_y,
                  contact_person_iou, contact_obstacle_iou],
     "fallen": true, "split": "train"}
"""

from __future__ import annotations

import json
from pathlib import Path

from vision_ai.models.perception.features import FEATURE_NAMES

SPLITS = ("train", "valid", "test")


class DatasetError(ValueError):
    """A dataset training cannot start on: raised instead of building a bad model."""


def load_dataset(path: Path) -> dict[str, tuple[list[list[float]], list[int]]]:
    rows: dict[str, tuple[list[list[float]], list[int]]] = {s: ([], []) for s in SPLITS}
    text = Path(path).read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise DatasetError(f"{path}:{number} is not JSON: {error}") from error
        split = record.get("split")
        if split not in rows:
            raise DatasetError(f"{path}:{number} split must be train, valid or test: {split!r}")
        features = record.get("features")
        if not isinstance(features, list) or len(features) != len(FEATURE_NAMES):
            raise DatasetError(
                f"{path}:{number} features must be the {len(FEATURE_NAMES)} contracted values: {FEATURE_NAMES}"
            )
        rows[split][0].append([float(value) for value in features])
        rows[split][1].append(1 if record.get("fallen") else 0)

    for split in SPLITS:
        features, labels = rows[split]
        if not features:
            raise DatasetError(f"the {split} split is empty (valid and test are needed too)")
        if sum(labels) == 0:
            raise DatasetError(f"the {split} split has no fallen examples, so no metric can be computed")
        if sum(labels) == len(labels):
            raise DatasetError(f"the {split} split has no upright examples, so no metric can be computed")
    return rows
