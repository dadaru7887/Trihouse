from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
POSTURES = {"standing", "fallen", "unknown"}
ENVIRONMENTS = {
    "normal_light", "low_light", "motion_blur", "color_shift",
    "condensation", "glare", "frost", "combined", "unknown",
}


class DatasetAuditError(ValueError):
    """Raised when the dataset cannot safely be used for training."""


@dataclass(frozen=True)
class SplitStats:
    images: int
    labels: int
    empty_labels: int
    instances: int
    person_instances: int


@dataclass(frozen=True)
class DatasetReport:
    data_yaml: str
    dataset_root: str
    dataset_status: str
    posture_status: str
    person_class_id: int
    names: list[str]
    fingerprint: str
    splits: dict[str, SplitStats]
    posture_counts: dict[str, dict[str, int]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_data_yaml(data_yaml: Path) -> tuple[Path, dict[str, Any], list[str], int]:
    data_yaml = data_yaml.expanduser().resolve()
    if not data_yaml.is_file():
        raise DatasetAuditError(f"data.yaml 파일이 없습니다: {data_yaml}")
    raw = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise DatasetAuditError("data.yaml 최상위 값은 mapping이어야 합니다")
    for key in ("train", "val", "test"):
        if not raw.get(key):
            raise DatasetAuditError(f"data.yaml에 {key} split이 없습니다")
    names_value = raw.get("names")
    if isinstance(names_value, dict):
        names = [str(names_value[key]) for key in sorted(names_value, key=lambda x: int(x))]
    elif isinstance(names_value, list):
        names = [str(value) for value in names_value]
    else:
        raise DatasetAuditError("data.yaml names는 list 또는 class ID mapping이어야 합니다")
    if "person" not in names:
        raise DatasetAuditError("data.yaml에 person class가 없습니다")
    nc = int(raw.get("nc", len(names)))
    if nc != len(names):
        raise DatasetAuditError(f"nc={nc}와 names 개수={len(names)}가 다릅니다")
    root_value = raw.get("path")
    root = (data_yaml.parent / str(root_value)).resolve() if root_value else data_yaml.parent
    return root, raw, names, names.index("person")


def _split_image_dir(root: Path, raw: dict[str, Any], yaml_dir: Path, key: str) -> Path:
    value = Path(str(raw[key])).expanduser()
    if value.is_absolute():
        return value.resolve()
    # Ultralytics resolves split paths against `path` when present, otherwise YAML dir.
    base = root if raw.get("path") else yaml_dir
    return (base / value).resolve()


def _parse_label(path: Path, class_count: int) -> list[dict[str, Any]]:
    instances: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        try:
            class_id = int(parts[0])
            coords = [float(value) for value in parts[1:]]
        except (ValueError, IndexError) as error:
            raise DatasetAuditError(f"{path}:{line_number} label 숫자 형식 오류") from error
        if class_id < 0 or class_id >= class_count:
            raise DatasetAuditError(f"{path}:{line_number} class ID {class_id}가 names 범위를 벗어납니다")
        if len(coords) < 6 or len(coords) % 2:
            raise DatasetAuditError(f"{path}:{line_number} polygon은 최소 3개 좌표쌍이어야 합니다")
        if any(value < 0.0 or value > 1.0 for value in coords):
            raise DatasetAuditError(f"{path}:{line_number} polygon 좌표는 0..1 범위여야 합니다")
        xs, ys = coords[0::2], coords[1::2]
        width, height = max(xs) - min(xs), max(ys) - min(ys)
        if width <= 0 or height <= 0:
            raise DatasetAuditError(f"{path}:{line_number} polygon 면적이 0입니다")
        instances.append({
            "class_id": class_id,
            "bbox_aspect_ratio": width / height,
            "bbox_width": width,
            "bbox_height": height,
        })
    return instances


def _read_manifest(
    manifest: Path | None,
    dataset_root: Path,
    image_to_split: dict[Path, str],
) -> tuple[dict[str, dict[str, int]], dict[Path, tuple[str, str]]]:
    counts = {split: {posture: 0 for posture in sorted(POSTURES)} for split in ("train", "valid", "test")}
    assignments: dict[Path, tuple[str, str]] = {}
    if manifest is None:
        return counts, assignments
    manifest = manifest.expanduser().resolve()
    if not manifest.is_file():
        raise DatasetAuditError(f"posture manifest 파일이 없습니다: {manifest}")
    with manifest.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"image", "posture", "environment"}
        if not required.issubset(reader.fieldnames or []):
            raise DatasetAuditError(f"posture manifest 필수 열: {sorted(required)}")
        for row_number, row in enumerate(reader, 2):
            image = (dataset_root / row["image"]).resolve()
            posture, environment = row["posture"].strip(), row["environment"].strip()
            if image not in image_to_split:
                raise DatasetAuditError(f"manifest {row_number}: dataset split 밖의 image: {row['image']}")
            if image in assignments:
                raise DatasetAuditError(f"manifest {row_number}: 중복 image: {row['image']}")
            if posture not in POSTURES:
                raise DatasetAuditError(f"manifest {row_number}: 허용되지 않은 posture: {posture}")
            if environment not in ENVIRONMENTS:
                raise DatasetAuditError(f"manifest {row_number}: 허용되지 않은 environment: {environment}")
            assignments[image] = (posture, environment)
            counts[image_to_split[image]][posture] += 1
    return counts, assignments


def audit_dataset(
    data_yaml: Path | str,
    output_dir: Path | str,
    posture_manifest: Path | str | None = None,
    allow_posture_gap: bool = False,
    min_fallen_per_eval_split: int = 10,
) -> DatasetReport:
    data_yaml = Path(data_yaml)
    output_dir = Path(output_dir)
    manifest_path = Path(posture_manifest) if posture_manifest else None
    root, raw, names, person_id = _load_data_yaml(data_yaml)
    output_dir.mkdir(parents=True, exist_ok=True)

    fingerprint = hashlib.sha256()
    fingerprint.update(data_yaml.resolve().read_bytes())
    hashes: dict[str, tuple[str, Path]] = {}
    image_to_split: dict[Path, str] = {}
    rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    split_stats: dict[str, SplitStats] = {}

    for canonical, yaml_key in (("train", "train"), ("valid", "val"), ("test", "test")):
        image_dir = _split_image_dir(root, raw, data_yaml.resolve().parent, yaml_key)
        if not image_dir.is_dir():
            raise DatasetAuditError(f"{canonical} image 디렉터리가 없습니다: {image_dir}")
        label_dir = image_dir.parent / "labels"
        images = sorted(path for path in image_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)
        image_stems = {path.stem for path in images}
        orphan_labels = sorted(
            path for path in label_dir.glob("*.txt") if path.stem not in image_stems
        ) if label_dir.is_dir() else []
        if orphan_labels:
            raise DatasetAuditError(f"image가 없는 label 파일이 있습니다: {orphan_labels[0]}")
        empty_count = instance_count = person_count = 0
        for image in images:
            if cv2.imread(str(image)) is None:
                raise DatasetAuditError(f"읽을 수 없는 image: {image}")
            label = label_dir / f"{image.stem}.txt"
            if not label.is_file():
                raise DatasetAuditError(f"image에 대응하는 label 파일이 없습니다: {image}")
            content_hash = _sha256(image)
            if content_hash in hashes and hashes[content_hash][0] != canonical:
                other_split, other_path = hashes[content_hash]
                raise DatasetAuditError(
                    f"split 사이 image content 중복: {other_split}/{other_path.name}, {canonical}/{image.name}"
                )
            hashes[content_hash] = (canonical, image)
            image_to_split[image.resolve()] = canonical
            instances = _parse_label(label, len(names))
            if not instances:
                empty_count += 1
            for index, instance in enumerate(instances):
                instance_count += 1
                is_person = instance["class_id"] == person_id
                person_count += int(is_person)
                row = {
                    "split": canonical,
                    "image": str(image.relative_to(root)),
                    "label": str(label.relative_to(root)),
                    "instance_index": index,
                    "class_id": instance["class_id"],
                    "class_name": names[instance["class_id"]],
                    "bbox_aspect_ratio": round(instance["bbox_aspect_ratio"], 8),
                }
                rows.append(row)
                if is_person:
                    candidate_rows.append({**row, "posture": "unknown"})
            for path in (image, label):
                fingerprint.update(str(path.relative_to(root)).encode())
                fingerprint.update(_sha256(path).encode())
        split_stats[canonical] = SplitStats(
            images=len(images), labels=len(images), empty_labels=empty_count,
            instances=instance_count, person_instances=person_count,
        )

    posture_counts, assignments = _read_manifest(manifest_path, root, image_to_split)
    for row in candidate_rows:
        image = (root / row["image"]).resolve()
        if image in assignments:
            row["posture"], row["environment"] = assignments[image]
        else:
            row["environment"] = "unknown"
    evaluable = all(
        posture_counts[split]["fallen"] >= min_fallen_per_eval_split
        for split in ("valid", "test")
    )
    posture_status = "EVALUABLE" if evaluable else "NOT_EVALUABLE"
    if not evaluable and not allow_posture_gap:
        raise DatasetAuditError(
            "valid/test의 confirmed fallen 표본이 부족합니다. detection-only 학습은 "
            "--allow-posture-gap을 명시하세요"
        )

    report = DatasetReport(
        data_yaml=str(data_yaml.expanduser().resolve()), dataset_root=str(root),
        dataset_status="VALID", posture_status=posture_status,
        person_class_id=person_id, names=names, fingerprint=fingerprint.hexdigest(),
        splits=split_stats, posture_counts=posture_counts,
    )
    (output_dir / "dataset_report.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_csv(output_dir / "instances.csv", rows)
    _write_csv(output_dir / "posture_candidates.csv", candidate_rows)
    _write_contact_sheet(output_dir / "contact_sheets/posture_candidates.jpg", root, candidate_rows)
    return report


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_contact_sheet(path: Path, root: Path, rows: list[dict[str, Any]]) -> None:
    """Write a bounded, deterministic posture-review sheet without changing source images."""
    best_by_image: dict[str, dict[str, Any]] = {}
    for row in rows:
        previous = best_by_image.get(row["image"])
        if previous is None or row["bbox_aspect_ratio"] > previous["bbox_aspect_ratio"]:
            best_by_image[row["image"]] = row
    selected = sorted(
        best_by_image.values(),
        key=lambda row: (-float(row["bbox_aspect_ratio"]), row["image"]),
    )[:40]
    tile_w, tile_h, columns = 240, 180, 4
    count = max(1, len(selected))
    canvas = np.full(((count + columns - 1) // columns * tile_h, columns * tile_w, 3), 245, dtype=np.uint8)
    for index, row in enumerate(selected):
        image = cv2.imread(str(root / row["image"]))
        if image is None:
            continue
        scale = min(tile_w / image.shape[1], (tile_h - 36) / image.shape[0])
        resized = cv2.resize(image, (max(1, int(image.shape[1] * scale)), max(1, int(image.shape[0] * scale))))
        x0, y0 = index % columns * tile_w, index // columns * tile_h
        canvas[y0:y0 + resized.shape[0], x0:x0 + resized.shape[1]] = resized
        label = f"{row['split']} ratio={float(row['bbox_aspect_ratio']):.2f}"
        cv2.putText(canvas, label, (x0 + 4, y0 + tile_h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (20, 20, 20), 1)
        cv2.putText(canvas, Path(row["image"]).name[:27], (x0 + 4, y0 + tile_h - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (20, 20, 20), 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), canvas):
        raise DatasetAuditError(f"contact sheet 저장 실패: {path}")
