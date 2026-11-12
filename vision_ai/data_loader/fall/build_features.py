"""Turn the Roboflow fallen export into the feature JSONL the classifier trains on.

    # from the ground-truth polygons: no weights needed
    python -m vision_ai.data_loader.fall.build_features \
        --export data/pinky_camera/fallen \
        --merged data/pinky_camera/merged \
        --out runs/fall/features.jsonl

    # from what the segmentation model actually predicts -- the operational one
    python -m vision_ai.data_loader.fall.build_features \
        --export data/pinky_camera/fallen \
        --merged data/pinky_camera/merged \
        --out runs/fall/features_predicted.jsonl \
        --masks predicted --weights runs/perception/<run>/train/weights/best.pt

Flow: read each export frame's polygons -> rasterise them into masks (or match
them to the model's predicted masks) -> compute FEATURE_NAMES (+ diagnostics) per person ->
write one JSONL row per person, tagged with the split the merged dataset put
that frame in.

Two things this exists to get right:

**Posture comes from the export, not the merged dataset.** Merging collapsed
Fallen and Standing into `person` for segmentation, so merged/ can no longer
say which instance fell; posture_manifest.csv is per image, not per instance.

**The split comes from the merged dataset.** Splitting again here would put
frames the detector trained on into the classifier's test, and with
`--masks predicted` those are frames the detector has memorised.

`--masks predicted` is the one to deploy: at inference the classifier sees the
model's masks, whose edges are cut and smoothed compared with a polygon, and a
threshold chosen on ground truth is not the best one for them.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from vision_ai.models.perception.features import (
    FEATURE_NAMES, diagnostic_features, geometric_features,
)

SPLITS = ("train", "valid", "test")

# Roboflow keeps the source video and its timestamp in the filename; the
# episode is what cross-validation holds out, since adjacent frames of one
# recording are near identical.
_EPISODE = re.compile(r"dataset_video_(\d{8}_\d{6})")
LEGACY_EPISODE = "legacy_frames"


def _episode_of(filename: str) -> str:
    """Return the recording a frame came from, or LEGACY_EPISODE."""
    match = _EPISODE.search(filename)
    return match.group(1) if match else LEGACY_EPISODE

# Roboflow class names in the fallen export. Obstacle is context for the
# contact features, never a row of its own.
FALLEN_NAMES = frozenset({"fallen"})
UPRIGHT_NAMES = frozenset({"standing"})

# Class ids the feature code expects, matching the merged dataset.
PERSON_CLASS_ID = 1
OBSTACLE_CLASS_ID = 0

# An IoU below this is not the same instance, so a ground-truth person with no
# predicted match is a detection failure, not a classifier sample.
MATCH_IOU = 0.3


@dataclass(frozen=True)
class Instance:
    """One labelled object: its mask, its class, and whether it is a fallen person.

    `fallen` is None for anything that is not a person, which is how the
    builder tells context apart from a training row.
    """

    class_name: str
    class_id: int
    fallen: bool | None
    mask: Any


def _rasterise(polygon: Sequence[float], shape: tuple[int, int]):
    """Fill a normalised YOLO polygon into a bool mask of `shape`."""
    import cv2

    height, width = shape
    points = np.asarray(polygon, dtype=np.float32).reshape(-1, 2)
    points[:, 0] *= width
    points[:, 1] *= height
    canvas = np.zeros(shape, dtype=np.uint8)
    cv2.fillPoly(canvas, [points.astype(np.int32)], 1)
    return canvas.astype(bool)


def instances_from_label(text: str, names: Sequence[str],
                         shape: tuple[int, int]) -> list[Instance]:
    """Parse one YOLO segmentation label file into instances with a posture."""
    instances = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 7:                      # class + at least 3 points
            continue
        name = names[int(parts[0])]
        lowered = name.strip().lower()
        if lowered in FALLEN_NAMES:
            fallen, class_id = True, PERSON_CLASS_ID
        elif lowered in UPRIGHT_NAMES:
            fallen, class_id = False, PERSON_CLASS_ID
        else:
            fallen, class_id = None, OBSTACLE_CLASS_ID
        instances.append(Instance(name, class_id, fallen,
                                  _rasterise([float(v) for v in parts[1:]], shape)))
    return instances


def split_index(merged_root: Path) -> dict[str, str]:
    """Map image filename -> split, as the merged dataset assigned it."""
    index = {}
    for split in SPLITS:
        directory = Path(merged_root) / split / "images"
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            index[path.name] = split
    if not index:
        raise ValueError(f"no split images under {merged_root}")
    return index


def _mask_iou(a, b) -> float:
    """IoU of two bool masks; 0.0 when either is empty."""
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


def _predicted_masks(image_path: Path, detector) -> list[Instance]:
    """Detections from the segmentation model, shaped like label instances."""
    import cv2

    frame = cv2.imread(str(image_path))
    return [Instance("person" if d.class_id == PERSON_CLASS_ID else "obstacle",
                     d.class_id, None, d.mask)
            for d in detector.detect(frame)]


def _match(target: Instance, candidates: Sequence[Instance]) -> Instance | None:
    """The predicted instance overlapping `target` most, if it overlaps enough."""
    best, best_iou = None, 0.0
    for candidate in candidates:
        iou = _mask_iou(target.mask, candidate.mask)
        if iou > best_iou:
            best, best_iou = candidate, iou
    return best if best_iou >= MATCH_IOU else None


def build_features(export_root: Path, merged_root: Path, out_path: Path,
                   masks: str = "gt", weights: Path | None = None,
                   device: str = "auto") -> dict:
    """Write the feature JSONL and return a report of what went into it.

    With `masks="predicted"`, each ground-truth person is matched to the
    detection covering it; a person the model missed is dropped rather than
    scored, since that is a segmentation failure, not a classifier one.
    """
    import cv2
    import yaml

    export_root, merged_root, out_path = Path(export_root), Path(merged_root), Path(out_path)
    names = yaml.safe_load((export_root / "data.yaml").read_text(encoding="utf-8"))["names"]
    if isinstance(names, dict):
        names = [names[key] for key in sorted(names)]
    placement = split_index(merged_root)

    detector = None
    if masks == "predicted":
        if weights is None:
            raise ValueError("--masks predicted needs --weights")
        from vision_ai.models.perception.detector import Detector, DetectorConfig

        detector = Detector(Path(weights), DetectorConfig(person_class_id=PERSON_CLASS_ID,
                                                          device=device))
        detector.load()
    elif masks != "gt":
        raise ValueError(f"unknown mask source: {masks}")

    report = {"rows": 0, "fallen": 0, "upright": 0, "per_split": {s: 0 for s in SPLITS},
              "skipped_not_in_split": 0, "skipped_undetected": 0, "skipped_empty_mask": 0,
              "masks": masks}
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as handle:
        for split in SPLITS:
            labels_dir = export_root / split / "labels"
            if not labels_dir.is_dir():
                continue
            for label_path in sorted(labels_dir.iterdir()):
                image_path = export_root / split / "images" / f"{label_path.stem}.jpg"
                if not image_path.is_file():
                    continue
                # The merged run decided the split; the export's own is ignored.
                assigned = placement.get(image_path.name)
                if assigned is None:
                    report["skipped_not_in_split"] += 1
                    continue
                image = cv2.imread(str(image_path))
                if image is None:
                    continue
                shape = image.shape[:2]
                truth = instances_from_label(
                    label_path.read_text(encoding="utf-8"), names, shape)
                context = (_predicted_masks(image_path, detector)
                           if detector is not None else truth)

                for target in truth:
                    if target.fallen is None:           # obstacles are context only
                        continue
                    source = target
                    if detector is not None:
                        matched = _match(target, context)
                        if matched is None:
                            report["skipped_undetected"] += 1
                            continue
                        source = Instance(target.class_name, PERSON_CLASS_ID,
                                          target.fallen, matched.mask)
                    values = geometric_features(source.mask, image.shape)
                    if values is None:
                        report["skipped_empty_mask"] += 1
                        continue
                    # Named, not positional: the contract order lives in
                    # FEATURE_NAMES, and the diagnostics ride alongside so the
                    # removed features can be re-measured without another pass.
                    named = dict(zip(FEATURE_NAMES, (float(v) for v in values)))
                    named.update(diagnostic_features(source.mask, image.shape))
                    handle.write(json.dumps({
                        "features": named,
                        "fallen": bool(target.fallen),
                        "split": assigned,
                        "episode": _episode_of(image_path.name),
                        "image": f"{assigned}/images/{image_path.name}",
                    }) + "\n")
                    report["rows"] += 1
                    report["per_split"][assigned] += 1
                    report["fallen" if target.fallen else "upright"] += 1

    if report["rows"] == 0:
        out_path.unlink(missing_ok=True)
        raise ValueError(
            f"no person instances were written from {export_root}; "
            "the export has no Fallen/Standing labels the merged split covers")
    return report


def build_parser() -> argparse.ArgumentParser:
    """Define the command line: which export, which split map, which masks."""
    parser = argparse.ArgumentParser(
        description="Build the fall-classifier feature JSONL from a Roboflow export")
    parser.add_argument("--export", type=Path, required=True,
                        help="Roboflow export holding Fallen/Standing labels")
    parser.add_argument("--merged", type=Path, required=True,
                        help="Merged dataset, which decides each frame's split")
    parser.add_argument("--out", type=Path, required=True, help="JSONL to write")
    parser.add_argument("--masks", choices=("gt", "predicted"), default="gt",
                        help="gt uses the labelled polygons; predicted uses the "
                             "segmentation model's masks, which is what inference sees")
    parser.add_argument("--weights", type=Path,
                        help="Segmentation weights, required by --masks predicted")
    parser.add_argument("--device", default="auto",
                        help="auto (cuda > mps > cpu), cpu, mps or a GPU index")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Build the JSONL and print what went into it."""
    from vision_ai.utils.run_logging import setup_logging

    args = build_parser().parse_args(argv)
    logger = setup_logging(args.out.parent)
    logger.info("building fall features | export=%s | masks=%s", args.export, args.masks)
    report = build_features(args.export, args.merged, args.out,
                            masks=args.masks, weights=args.weights, device=args.device)
    logger.info("wrote %s rows to %s", report["rows"], args.out)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
