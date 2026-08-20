import csv
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from vision_system.training.dataset_audit import DatasetAuditError, audit_dataset


def make_dataset(root: Path, *, duplicate: bool = False) -> Path:
    for index, split in enumerate(("train", "valid", "test")):
        (root / split / "images").mkdir(parents=True)
        (root / split / "labels").mkdir(parents=True)
        image = np.full((24, 32, 3), 30 + index, dtype=np.uint8)
        if duplicate and split == "test":
            image[:] = 31
        cv2.imwrite(str(root / split / "images" / f"{split}.jpg"), image)
        (root / split / "labels" / f"{split}.txt").write_text(
            "1 0.25 0.20 0.75 0.20 0.75 0.80 0.25 0.80\n",
            encoding="utf-8",
        )
    data = {
        "train": "train/images",
        "val": "valid/images",
        "test": "test/images",
        "nc": 2,
        "names": ["obstacle", "person"],
    }
    path = root / "data.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def write_manifest(path: Path, rows: list[tuple[str, str, str]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["image", "posture", "environment"])
        writer.writerows(rows)
    return path


def test_audit_writes_deterministic_report_and_candidates(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")
    output = tmp_path / "audit"

    report = audit_dataset(data, output, allow_posture_gap=True)

    assert report.dataset_status == "VALID"
    assert report.posture_status == "NOT_EVALUABLE"
    assert report.person_class_id == 1
    assert report.splits["train"].images == 1
    assert report.splits["test"].person_instances == 1
    assert len(report.fingerprint) == 64
    assert (output / "dataset_report.json").is_file()
    assert (output / "instances.csv").is_file()
    assert (output / "posture_candidates.csv").is_file()
    assert cv2.imread(str(output / "contact_sheets/posture_candidates.jpg")) is not None


@pytest.mark.parametrize(
    "bad_label, expected",
    [
        ("2 0.1 0.1 0.2 0.1 0.2 0.2\n", "class ID"),
        ("1 0.1 0.1 1.2 0.1 0.2 0.2\n", "0..1"),
        ("1 0.1 0.1 0.2 0.2\n", "polygon"),
    ],
)
def test_audit_rejects_invalid_polygon_labels(
    tmp_path: Path, bad_label: str, expected: str
) -> None:
    data = make_dataset(tmp_path / "dataset")
    (tmp_path / "dataset/train/labels/train.txt").write_text(bad_label, encoding="utf-8")

    with pytest.raises(DatasetAuditError, match=expected):
        audit_dataset(data, tmp_path / "audit", allow_posture_gap=True)


def test_audit_rejects_missing_label_pair(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")
    (tmp_path / "dataset/test/labels/test.txt").unlink()

    with pytest.raises(DatasetAuditError, match="label.*없습니다"):
        audit_dataset(data, tmp_path / "audit", allow_posture_gap=True)


def test_audit_rejects_orphan_label_without_image(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")
    (tmp_path / "dataset/valid/labels/orphan.txt").write_text(
        "1 0.1 0.1 0.2 0.1 0.2 0.2\n", encoding="utf-8"
    )

    with pytest.raises(DatasetAuditError, match="image가 없는 label"):
        audit_dataset(data, tmp_path / "audit", allow_posture_gap=True)


def test_audit_rejects_cross_split_duplicate_image_content(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset", duplicate=True)

    with pytest.raises(DatasetAuditError, match="split.*중복"):
        audit_dataset(data, tmp_path / "audit", allow_posture_gap=True)


def test_audit_requires_explicit_override_without_fallen_posture(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")

    with pytest.raises(DatasetAuditError, match="allow-posture-gap"):
        audit_dataset(data, tmp_path / "audit", allow_posture_gap=False)


def test_audit_accepts_manifest_with_minimum_fallen_per_eval_split(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")
    rows = []
    # The fixture has one image per split; repeated instances are prohibited, so use a
    # deliberately lower test-only gate to prove split accounting.
    rows.extend([
        ("valid/images/valid.jpg", "fallen", "normal_light"),
        ("test/images/test.jpg", "fallen", "low_light"),
    ])
    manifest = write_manifest(tmp_path / "posture.csv", rows)

    report = audit_dataset(
        data,
        tmp_path / "audit",
        posture_manifest=manifest,
        allow_posture_gap=False,
        min_fallen_per_eval_split=1,
    )

    assert report.posture_status == "EVALUABLE"
    assert report.posture_counts["valid"]["fallen"] == 1
    assert report.posture_counts["test"]["fallen"] == 1
