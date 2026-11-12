"""Per-person rows carrying the A/B/C fall features of the same instances.

    from vision_ai.data_loader.fall.compare_rows import build_rows
    rows, unmatched, report = build_rows(export_root, masks="gt")
    rows, unmatched, report = build_rows(export_root, masks="predicted",
                                         weights=Path("selected_model.json"))

Called by `models/perception/trainer/fall_compare.py`; not run on its own.

Flow per export image: parse the label file -> refuse the image if any line is
malformed (its context would be partial) -> take each Fallen/Standing
instance as a row -> measure the three groups on one mask:

    A  LEGACY_FEATURE_NAMES   polygon vertices + bbox contact (upstream)
    B  aspect_ratio           features.geometric_features on the raster mask
    C  aspect_ratio, axis_horizontality

`masks="gt"` uses the labelled polygon. `masks="predicted"` runs YOLOE,
matches each labelled person to one predicted person by mask IoU, and keeps a
labelled person with no match as a row with `detected=False` and no features.
Predicted people matched to no label come back in `unmatched`.

The split is the export's own folder. When `merged_root` is given, every image
must sit in the same split there, so a detector trained on that merge never
saw a valid/test frame.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import numpy as np

from vision_ai.data_loader.fall.build_features import (
    FALLEN_NAMES, PERSON_CLASS_ID, UPRIGHT_NAMES, _episode_of, _rasterise, split_index,
)
from vision_ai.models.perception.features import geometric_features
from vision_ai.models.perception.legacy_features import (
    LEGACY_FEATURE_NAMES, contact_from_boxes, contact_from_instances, legacy_geometric,
)

SPLITS = ("train", "valid", "test")
GROUPS = {
    "A": LEGACY_FEATURE_NAMES,
    "B": ("aspect_ratio",),
    "C": ("aspect_ratio", "axis_horizontality"),
}
OBSTACLE_NAMES = frozenset({"obstacle"})

# Minimum mask IoU for a predicted person to be the same instance as a label.
MATCH_IOU = 0.3
# YOLOE settings, matching DetectorConfig defaults.
CONFIDENCE = 0.25
IMAGE_SIZE = 640


def parse_label(text: str, names: Sequence[str]):
    """(class_name, polygon) per line, or None when any line is malformed.

    Malformed means: fewer than 3 points, an odd coordinate count, or a class
    id outside data.yaml. Upstream skipped such lines silently, which would
    turn a missing neighbour into a contact IoU of 0.
    """
    instances = []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        coords = parts[1:]
        class_id = int(parts[0])
        if len(coords) < 6 or len(coords) % 2 or not 0 <= class_id < len(names):
            return None
        values = [float(v) for v in coords]
        instances.append((names[class_id], list(zip(values[0::2], values[1::2]))))
    return instances


def _posture(name: str) -> bool | None:
    """True for Fallen, False for Standing, None for an obstacle."""
    lowered = name.strip().lower()
    if lowered in FALLEN_NAMES:
        return True
    if lowered in UPRIGHT_NAMES:
        return False
    if lowered in OBSTACLE_NAMES:
        return None
    raise ValueError(f"unknown class in fallen export: {name}")


def _mask_iou(a, b) -> float:
    """IoU of two bool masks; 0.0 when both are empty."""
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


def _bc_features(mask, shape) -> dict[str, float] | None:
    """Group B/C values from a raster mask, or None for an empty mask."""
    values = geometric_features(mask, shape)
    if values is None:
        return None
    return {"aspect_ratio": float(values[0]), "axis_horizontality": float(values[1])}


def _images(export_root: Path):
    """(split, image_path, label_path) for every export image, in a fixed order."""
    for split in SPLITS:
        directory = export_root / split / "images"
        if not directory.is_dir():
            continue
        for image in sorted(directory.iterdir()):
            if image.suffix.lower() in (".jpg", ".jpeg", ".png"):
                yield split, image, export_root / split / "labels" / f"{image.stem}.txt"


def check_sessions(export_root: Path, merged_root: Path | None) -> dict[str, list[str]]:
    """Episodes per split; raise if one spans two splits or the merge disagrees."""
    placed: dict[str, str] = {}
    disagree = []
    merged = split_index(merged_root) if merged_root else None
    for split, image, _ in _images(export_root):
        episode = _episode_of(image.name)
        if placed.setdefault(episode, split) != split:
            raise ValueError(f"episode {episode} appears in {placed[episode]} and {split}")
        if merged is not None and merged.get(image.name) != split:
            disagree.append((image.name, split, merged.get(image.name)))
    if disagree:
        raise ValueError(f"{len(disagree)} images sit in a different split in the merge, "
                         f"e.g. {disagree[:3]}")
    return {s: sorted(e for e, p in placed.items() if p == s) for s in SPLITS}


class _Predictor:
    """YOLOE wrapper returning classes, boxes, polygons and frame-sized masks."""

    def __init__(self, weights: Path, device: str):
        from ultralytics import YOLOE

        from vision_ai.models.perception.detector import resolve_weights
        from vision_ai.utils.device import resolve_device

        self.weights = resolve_weights(weights)
        self.device = resolve_device(device).resolved
        self.model = YOLOE(str(self.weights))

    def __call__(self, frame):
        import cv2

        result = self.model.predict(frame, conf=CONFIDENCE, imgsz=IMAGE_SIZE,
                                    device=self.device, verbose=False)[0]
        if result.masks is None or not len(result.masks.data):
            return [], [], [], []
        height, width = frame.shape[:2]
        classes = result.boxes.cls.cpu().numpy().astype(int).tolist()
        boxes = result.boxes.xyxyn.cpu().numpy().tolist()
        polygons = [p.tolist() for p in result.masks.xyn]
        masks = []
        for raw in result.masks.data.cpu().numpy():
            # Resize to the frame so normalised measurements use the right shape.
            if raw.shape != (height, width):
                raw = cv2.resize(raw, (width, height), interpolation=cv2.INTER_NEAREST)
            masks.append(raw > 0.5)
        return classes, boxes, polygons, masks


def _match(truth_masks, pred_masks) -> dict[int, tuple[int, float]]:
    """Greedy one-to-one match, highest mask IoU first: truth index -> (pred, IoU)."""
    pairs = sorted(((_mask_iou(t, p), ti, pi) for ti, t in enumerate(truth_masks)
                    for pi, p in enumerate(pred_masks)), reverse=True)
    taken_t, taken_p, out = set(), set(), {}
    for iou, ti, pi in pairs:
        if iou < MATCH_IOU:
            break
        if ti in taken_t or pi in taken_p:
            continue
        taken_t.add(ti)
        taken_p.add(pi)
        out[ti] = (pi, iou)
    return out


def build_rows(export_root: Path, masks: str = "gt", weights: Path | None = None,
               merged_root: Path | None = None, device: str = "auto"):
    """Return (rows, unmatched_predictions, report) for one mask source."""
    import cv2
    import yaml

    export_root = Path(export_root)
    names = yaml.safe_load((export_root / "data.yaml").read_text(encoding="utf-8"))["names"]
    if isinstance(names, dict):
        names = [names[k] for k in sorted(names)]
    sessions = check_sessions(export_root, Path(merged_root) if merged_root else None)

    predictor = None
    if masks == "predicted":
        if weights is None:
            raise ValueError("masks='predicted' needs weights")
        predictor = _Predictor(Path(weights), device)
    elif masks != "gt":
        raise ValueError(f"unknown mask source: {masks}")

    rows: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    skipped = {"missing_label_file": 0, "malformed_label_image": 0,
               "malformed_label_persons": 0, "empty_mask": 0, "unreadable_image": 0}
    coverage: dict[str, dict[str, Any]] = {}

    for split, image_path, label_path in _images(export_root):
        if not label_path.is_file():
            skipped["missing_label_file"] += 1
            continue
        instances = parse_label(label_path.read_text(encoding="utf-8"), names)
        if instances is None:
            # Context is partial; every person in the image is dropped for all groups.
            text = label_path.read_text(encoding="utf-8")
            skipped["malformed_label_image"] += 1
            skipped["malformed_label_persons"] += sum(
                1 for line in text.splitlines() if line.split()
                and line.split()[0].isdigit() and int(line.split()[0]) < len(names)
                and _posture(names[int(line.split()[0])]) is not None)
            continue
        frame = cv2.imread(str(image_path))
        if frame is None:
            skipped["unreadable_image"] += 1
            continue
        shape = frame.shape[:2]
        base = {"image": f"{split}/images/{image_path.name}", "split": split,
                "episode": _episode_of(image_path.name)}
        people = [(i, name, poly, _posture(name)) for i, (name, poly) in enumerate(instances)
                  if _posture(name) is not None]
        # Label coverage per episode: shows whether contact context was annotated.
        tally = coverage.setdefault(base["episode"], {
            "split": split, "images": 0, "person_labels": 0, "obstacle_labels": 0,
            "images_with_obstacle": 0, "images_with_2plus_people": 0})
        obstacles = len(instances) - len(people)
        tally["images"] += 1
        tally["person_labels"] += len(people)
        tally["obstacle_labels"] += obstacles
        tally["images_with_obstacle"] += int(obstacles > 0)
        tally["images_with_2plus_people"] += int(len(people) > 1)
        truth_masks = [_rasterise([v for xy in poly for v in xy], shape) for _, _, poly, _ in people]

        if predictor is None:
            for (index, _, poly, fallen), mask in zip(people, truth_masks):
                bc = _bc_features(mask, frame.shape)
                if bc is None:
                    skipped["empty_mask"] += 1
                    continue
                values = dict(zip(LEGACY_FEATURE_NAMES,
                                  (*legacy_geometric(poly), *contact_from_instances(poly, instances))))
                values.update(bc)
                rows.append({**base, "instance": index, "fallen": fallen, "detected": True,
                             "match_iou": None, "features": values,
                             "box": [min(x for x, _ in poly), min(y for _, y in poly),
                                     max(x for x, _ in poly), max(y for _, y in poly)]})
            continue

        classes, boxes, polygons, pred_masks = predictor(frame)
        person_idx = [i for i, c in enumerate(classes) if c == PERSON_CLASS_ID]
        matches = _match(truth_masks, [pred_masks[i] for i in person_idx])
        used = set()
        for t, (index, _, poly, fallen) in enumerate(people):
            row = {**base, "instance": index, "fallen": fallen,
                   "box": [min(x for x, _ in poly), min(y for _, y in poly),
                           max(x for x, _ in poly), max(y for _, y in poly)]}
            if t not in matches:
                rows.append({**row, "detected": False, "match_iou": None, "features": None})
                continue
            local, iou = matches[t]
            pi = person_idx[local]
            used.add(pi)
            rows.append({**row, "detected": True, "match_iou": round(iou, 4),
                         "features": _predicted_values(pi, classes, boxes, polygons,
                                                       pred_masks, frame.shape),
                         "pred_polygon": polygons[pi]})
        for pi in person_idx:
            if pi not in used:
                unmatched.append({**base, "features": _predicted_values(
                    pi, classes, boxes, polygons, pred_masks, frame.shape),
                    "box": boxes[pi], "pred_polygon": polygons[pi]})

    report = {"masks": masks, "weights": str(predictor.weights) if predictor else None,
              "sessions": sessions, "skipped": skipped, "rows": len(rows),
              "label_coverage": dict(sorted(coverage.items())),
              "unmatched_predictions": len(unmatched)}
    return rows, unmatched, report


def _predicted_values(index, classes, boxes, polygons, masks, shape) -> dict | None:
    """All three groups for one predicted person, or None if any is unmeasurable."""
    polygon = polygons[index]
    bc = _bc_features(masks[index], shape)
    if len(polygon) < 3 or bc is None:
        return None
    values = dict(zip(LEGACY_FEATURE_NAMES, (
        *legacy_geometric(polygon),
        *contact_from_boxes(boxes[index], boxes, classes, index, PERSON_CLASS_ID))))
    values.update(bc)
    return values


def context_audit(rows: Sequence[dict]) -> dict[str, dict[str, Any]]:
    """Per-episode coverage of the contact inputs, for the report.

    Counts how often a row has another person or an obstacle overlapping it,
    so a contact feature that is zero almost everywhere is visible.
    """
    audit: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("features") is None:
            continue
        entry = audit.setdefault(row["episode"], {
            "split": row["split"], "persons": 0, "fallen": 0,
            "person_contact_nonzero": 0, "obstacle_contact_nonzero": 0})
        entry["persons"] += 1
        entry["fallen"] += int(row["fallen"])
        entry["person_contact_nonzero"] += int(row["features"]["contact_person_iou"] > 0)
        entry["obstacle_contact_nonzero"] += int(row["features"]["contact_obstacle_iou"] > 0)
    return dict(sorted(audit.items()))
