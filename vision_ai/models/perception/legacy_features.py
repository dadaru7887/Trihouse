"""The five fall features of the upstream dev_vision classifier, reproduced as-is.

    from vision_ai.models.perception.legacy_features import (
        LEGACY_FEATURE_NAMES, legacy_geometric, contact_from_instances,
        contact_from_boxes)

    geo = legacy_geometric(polygon)                         # 3 values
    touch = contact_from_instances(polygon, others)         # 2 values, ground truth
    touch = contact_from_boxes(box, boxes, classes, i, 1)   # 2 values, predictions
    values = (*geo, *touch)                                 # LEGACY_FEATURE_NAMES order

Comparison group A only; the deployed classifier reads `features.py`.
Source: origin/dev_vision fallen_detection_delivery/code/classifier_trainer.py
(`polygon_to_geometric_features`, `contact_features`, `contact_from_predictions`),
copied in `vision_ai/upstream/dev_vision/code/`. The input order is the one
`build_feature_matrix` concatenates: geometric first, then contact.

Everything is measured on 0..1 normalised polygon vertices and boxes, as
upstream did -- not on rasterised mask pixels like `features.py`.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

# Input order of the upstream bundle (configs/final_metrics.json).
LEGACY_FEATURE_NAMES = (
    "aspect_ratio_poly",        # polygon bbox width / height
    "pca_angle_deg",            # principal-axis angle of the vertices, 0..180
    "centroid_y",               # mean vertex y, 0 = top, 1 = bottom
    "contact_person_iou",       # max bbox IoU with another person
    "contact_obstacle_iou",     # max bbox IoU with an obstacle
)

# Upstream class-name sets used to tell a person from an obstacle.
FALLEN_CLASS_NAMES = {"fallen_person", "fallen person", "fallen", "person_fallen"}
NOT_FALLEN_CLASS_NAMES = {"non_fallen", "non-fallen", "not_fallen", "person", "standing"}

# An instance whose bbox IoU with the target reaches this is taken as the
# target itself and skipped (upstream rule).
SELF_IOU = 0.95


def legacy_geometric(polygon: Sequence[Sequence[float]]) -> tuple[float, float, float]:
    """(aspect_ratio, pca_angle_deg, centroid_y) of a normalised polygon."""
    pts = np.asarray(polygon, dtype=np.float64)
    xs, ys = pts[:, 0], pts[:, 1]
    width, height = xs.max() - xs.min(), ys.max() - ys.min()
    aspect_ratio = width / max(height, 1e-6)
    centroid_y = float(ys.mean())
    cov = np.cov((pts - pts.mean(axis=0)).T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    principal = eigvecs[:, np.argmax(eigvals)]
    angle_deg = float(np.degrees(np.arctan2(principal[1], principal[0])) % 180.0)
    # Upstream returned float32; cast through it so values match bit for bit.
    out = np.array([aspect_ratio, angle_deg, centroid_y], dtype=np.float32)
    return float(out[0]), float(out[1]), float(out[2])


def box_iou(a: Sequence[float], b: Sequence[float]) -> float:
    """IoU of two (x0, y0, x1, y1) boxes; 0.0 for an empty union."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    inter = max(0.0, min(ax1, bx1) - max(ax0, bx0)) * max(0.0, min(ay1, by1) - max(ay0, by0))
    union = (max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
             + max(0.0, bx1 - bx0) * max(0.0, by1 - by0) - inter)
    return inter / union if union > 0 else 0.0


def polygon_bbox(polygon: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
    """Axis-aligned (x0, y0, x1, y1) box of a polygon."""
    pts = np.asarray(polygon, dtype=np.float64)
    return float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())


def is_person_name(name: str) -> bool:
    """Upstream test for a person-type class name."""
    lowered = name.strip().lower()
    return lowered in NOT_FALLEN_CLASS_NAMES or lowered in FALLEN_CLASS_NAMES or "fallen" in lowered


def contact_from_instances(target: Sequence[Sequence[float]],
                           instances: Sequence[tuple[str, Sequence[Sequence[float]]]]
                           ) -> tuple[float, float]:
    """(person IoU, obstacle IoU) against every labelled instance in the image.

    `instances` is the whole label file, target included; the target drops out
    through SELF_IOU, as upstream did.
    """
    target_box = polygon_bbox(target)
    person_max = obstacle_max = 0.0
    for name, polygon in instances:
        iou = box_iou(target_box, polygon_bbox(polygon))
        if iou >= SELF_IOU:
            continue
        if is_person_name(name):
            person_max = max(person_max, iou)
        else:
            obstacle_max = max(obstacle_max, iou)
    return float(np.float32(person_max)), float(np.float32(obstacle_max))


def contact_from_boxes(target_box: Sequence[float], boxes: Sequence[Sequence[float]],
                       classes: Sequence[int], exclude_index: int,
                       person_class_id: int) -> tuple[float, float]:
    """(person IoU, obstacle IoU) against the other predicted detections."""
    person_max = obstacle_max = 0.0
    for index, (box, class_id) in enumerate(zip(boxes, classes)):
        if index == exclude_index:
            continue
        iou = box_iou(target_box, box)
        if int(class_id) == person_class_id:
            person_max = max(person_max, iou)
        else:
            obstacle_max = max(obstacle_max, iou)
    return float(np.float32(person_max)), float(np.float32(obstacle_max))
