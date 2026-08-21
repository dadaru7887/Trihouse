import csv
import json
import statistics
from pathlib import Path

import yaml


def _image_dir(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def analyze_labels(data_yaml: Path, output_dir: Path, small_threshold: float = 0.01) -> dict:
    data_yaml, output_dir = Path(data_yaml).resolve(), Path(output_dir).resolve()
    raw = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    root = (data_yaml.parent / raw.get("path", "")).resolve()
    names = list(raw["names"].values()) if isinstance(raw["names"], dict) else list(raw["names"])
    person_id = names.index("person")
    rows, splits = [], {}
    for split, key in (("train", "train"), ("valid", "val"), ("test", "test")):
        images = sorted(path for path in _image_dir(root, raw[key]).iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"})
        label_dir = _image_dir(root, raw[key]).parent / "labels"
        person_areas, person_vertices, person_images = [], [], 0
        class_counts = {name: 0 for name in names}
        empty = 0
        for image in images:
            label = label_dir / f"{image.stem}.txt"
            lines = [line for line in label.read_text(encoding="utf-8").splitlines() if line.strip()]
            empty += not lines
            has_person = False
            for index, line in enumerate(lines):
                values = line.split()
                class_id = int(values[0])
                coords = list(map(float, values[1:]))
                xs, ys = coords[0::2], coords[1::2]
                area = (max(xs) - min(xs)) * (max(ys) - min(ys))
                vertices = len(xs)
                class_counts[names[class_id]] += 1
                if class_id == person_id:
                    has_person = True
                    person_areas.append(area)
                    person_vertices.append(vertices)
                rows.append({"split": split, "image": str(image.relative_to(root)), "instance": index, "class_id": class_id, "class_name": names[class_id], "bbox_area_ratio": area, "vertices": vertices, "small": class_id == person_id and area < small_threshold})
            person_images += has_person
        splits[split] = {
            "images": len(images), "empty_labels": empty, "person_images": person_images,
            "negative_images": len(images) - person_images, "person_instances": len(person_areas),
            "small_person_instances": sum(area < small_threshold for area in person_areas),
            "person_bbox_area": {
                "min": min(person_areas) if person_areas else None,
                "median": statistics.median(person_areas) if person_areas else None,
                "max": max(person_areas) if person_areas else None,
            },
            "person_polygon_vertices_median": statistics.median(person_vertices) if person_vertices else None,
            "class_instances": class_counts,
        }
    report = {"schema_version": 1, "data_yaml": str(data_yaml), "small_object_threshold": small_threshold, "splits": splits}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "label_analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (output_dir / "label_instances.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["split"])
        writer.writeheader()
        writer.writerows(rows)
    return report
