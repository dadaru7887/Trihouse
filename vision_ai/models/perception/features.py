"""The five features the fall classifier reads, as the dev_vision bundle defines them.

    from vision_ai.models.perception.features import fallen_features
    values = fallen_features(target, others, frame_shape)   # -> 5 floats

**The coordinate basis is part of the contract.** Everything here is measured
on normalised 0..1 coordinates (ultralytics `masks.xyn` / `boxes.xyxyn`), the
basis the bundle was trained on. `robot/perception/posture.py` measures in
pixels and stays that way: its 0.9 threshold was set on pixel ratios.

The two bases differ on any non-square frame -- a 200x100 mask in a 640x480
frame has an aspect ratio of 2.0 in pixels and 1.5 normalised -- and
aspect_ratio carries the bundle's largest coefficient (+5.273), so feeding it
pixels would quietly break the strongest signal.

Order matters: features are passed positionally, and FEATURE_NAMES is written
into the trained bundle so a reordering is caught at load time.

    (aspect_ratio, pca_angle, centroid_y, contact_person_iou, contact_obstacle_iou)
"""

from __future__ import annotations

from typing import Any, Sequence

# As in the delivered bundle: an overlap above this means the mask is
# the target itself, not a second object touching it.
SELF_OVERLAP_IOU = 0.95

FEATURE_NAMES = (
    "aspect_ratio",
    "pca_angle",
    "centroid_y",
    "contact_person_iou",
    "contact_obstacle_iou",
)


def geometric_features(mask: Any, frame_shape: tuple[int, ...]) -> tuple[float, float, float] | None:
    """(aspect ratio, PCA axis angle in [0,180), centroid height), all normalised.

    `None` for an empty mask. The angle is the direction of the covariance
    matrix's leading eigenvector, which is the direction the body lies along.
    """
    import numpy as np

    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    height, width = float(frame_shape[0]), float(frame_shape[1])
    nx = xs / max(width, 1.0)
    ny = ys / max(height, 1.0)

    # Span counts pixels (+1), matching mask_geometry. The delivered bundle
    # measured polygon vertices and has no +1; on a 200px mask that is a 0.5%
    # difference, far below the mask's own jitter, and one definition of aspect
    # ratio across the repo is worth more than matching it exactly.
    span_x = float(xs.max() - xs.min() + 1) / max(width, 1.0)
    span_y = float(ys.max() - ys.min() + 1) / max(height, 1.0)
    aspect_ratio = span_x / max(span_y, 1e-6)
    centroid_y = float(ny.mean())

    points = np.stack([nx, ny])
    centered = points - points.mean(axis=1, keepdims=True)
    covariance = np.cov(centered)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    principal = eigenvectors[:, int(np.argmax(eigenvalues))]
    angle_deg = float(np.degrees(np.arctan2(principal[1], principal[0])) % 180.0)

    return aspect_ratio, angle_deg, centroid_y


def _normalized_box(mask: Any, frame_shape: tuple[int, ...]) -> tuple[float, float, float, float] | None:
    import numpy as np

    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    height, width = float(frame_shape[0]), float(frame_shape[1])
    return (
        float(xs.min()) / width, float(ys.min()) / height,
        float(xs.max()) / width, float(ys.max()) / height,
    )


def _box_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def contact_features(target: Any, detections: Sequence[Any], *,
                     person_class_id: int) -> tuple[float, float]:
    """(largest person-person contact IoU, largest person-obstacle contact IoU).

    A second signal for a slumped fall, where the aspect ratio barely moves.
    In the delivered recording it went from 0.000 before the slump to 0.05-0.13
    after, matching the ground-truth timeline over a stretch where aspect ratio
    said almost nothing.

    IoU survives an independent rescale of each axis, so pixels and normalised
    coordinates give the same number; it is measured normalised anyway to keep
    one basis across all five features.
    """
    frame_shape = target.mask.shape
    target_box = _normalized_box(target.mask, frame_shape)
    if target_box is None:
        return 0.0, 0.0
    person_max, obstacle_max = 0.0, 0.0
    for other in detections:
        if other is target:
            continue
        other_box = _normalized_box(other.mask, frame_shape)
        if other_box is None:
            continue
        iou = _box_iou(target_box, other_box)
        if iou >= SELF_OVERLAP_IOU:
            # Treat this as the target detected twice, as the bundle does.
            continue
        if other.class_id == person_class_id:
            person_max = max(person_max, iou)
        else:
            obstacle_max = max(obstacle_max, iou)
    return person_max, obstacle_max


def fallen_features(target: Any, detections: Sequence[Any], frame_shape: tuple[int, ...], *,
                    person_class_id: int) -> tuple[float, ...] | None:
    """The five values in the trained order, or `None` for an empty mask."""
    geometry = geometric_features(target.mask, frame_shape)
    if geometry is None:
        return None
    contact = contact_features(target, detections, person_class_id=person_class_id)
    return (*geometry, *contact)
