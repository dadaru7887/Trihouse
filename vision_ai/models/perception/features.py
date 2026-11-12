"""Shape features for the fall classifier, and how their evidence is combined.

    from vision_ai.models.perception.features import (
        geometric_features, combine_modes, window_score)

    values = geometric_features(mask, frame.shape)      # -> (aspect, horizontality)
    evidence = combine_modes({"aspect": p_a, "horiz": p_h})
    decided = window_score(recent_evidence)             # median over the window

A Lego robot cannot run a skeleton model, so posture is read from the
segmentation mask alone. Everything is measured on normalised 0..1 coordinates,
the basis the delivered bundle was trained on; `robot/perception/posture.py`
measures in pixels and stays that way, because its 0.9 threshold was set there.

Two features, one per fall posture they can see:

    aspect_ratio        bounding box width / height. Sees a body lying across
                        the frame; blind to one lying at 45 degrees, where the
                        axis-aligned box squares off.
    axis_horizontality  |cos| of the body axis. Sees the diagonal case.

Stored as |cos| rather than an angle because 0 and 180 degrees are the same
direction while sitting at opposite ends of a 0..180 range: a fallen body
scores near either end depending on which way the head points, and a linear
model can call one end fallen, never both. Measured on the pinky dataset the
raw angle scored AUC 0.459 against 0.962 for |cos|.

Modes are combined with max, not a weighted sum. A sum dilutes the mode the
other cannot see -- at equal recall the sum held 25 false positives where max
held 13, because catching the diagonal falls no longer required dropping the
aspect threshold far enough to sweep in standing people.

Removed after measuring them, all restorable once data exists:

    centroid_y          absolute height in frame. Tracks where the robot is
                        standing, not what the person is doing: valid AUC
                        0.805, test 0.508.
    elongation          spread along the body axis over spread across it. As
                        an OR term it took false positives from 13 to 35: a
                        distant standing person is stocky too.
    contact_person_iou  overlap with another person or an obstacle, for a
    contact_obstacle_iou slumped or tripped fall. Zero in 97% and 100% of
                        training rows, leaving StandardScaler a near-zero
                        variance to divide by and blowing the standardised
                        values up to 18.8 and 1.6e10.

The first two are still computed by `diagnostic_features` so they can be
re-measured on predicted masks without changing what the classifier consumes.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

FEATURE_NAMES = (
    "aspect_ratio",
    "axis_horizontality",
)

# Below this the two eigenvalues are close, the mask is a round blob, and its
# axis direction is numerical noise rather than a body orientation. Not used
# as a gate today: on this dataset it fires on 8 instances, all real falls that
# aspect_ratio already catches, so gating changed no decision.
MIN_ELONGATION_FOR_AXIS = 1.2


def _axes(mask: Any, frame_shape: tuple[int, ...]):
    """Principal axis and eigenvalues of the mask's pixel cloud, or None."""
    import numpy as np

    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    height, width = float(frame_shape[0]), float(frame_shape[1])
    points = np.stack([xs / max(width, 1.0), ys / max(height, 1.0)])
    covariance = np.cov(points - points.mean(axis=1, keepdims=True))
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = int(np.argmax(eigenvalues))
    return ys, xs, eigenvectors[:, order], float(max(eigenvalues[order], 0.0)), \
        float(max(eigenvalues[1 - order], 0.0))


def geometric_features(mask: Any, frame_shape: tuple[int, ...]) -> tuple[float, ...] | None:
    """The FEATURE_NAMES values in order, or `None` for an empty mask."""
    import numpy as np

    parts = _axes(mask, frame_shape)
    if parts is None:
        return None
    ys, xs, principal, _, _ = parts
    height, width = float(frame_shape[0]), float(frame_shape[1])

    # Span counts pixels (+1), matching robot/perception/posture.py. The
    # delivered bundle measured polygon vertices and has no +1; on a 200px mask
    # that is 0.5%, far below the mask's own jitter.
    span_x = float(xs.max() - xs.min() + 1) / max(width, 1.0)
    span_y = float(ys.max() - ys.min() + 1) / max(height, 1.0)
    aspect_ratio = span_x / max(span_y, 1e-6)

    # |cos| folds the axis onto one scale: 1 lying either way, 0 upright.
    horizontality = float(abs(principal[0] / max(np.hypot(*principal), 1e-12)))
    return aspect_ratio, horizontality


def diagnostic_features(mask: Any, frame_shape: tuple[int, ...]) -> dict[str, float]:
    """Measurements kept for comparison, deliberately outside the contract.

    Empty for an empty mask, so a caller can merge it without checking.
    """
    import numpy as np

    parts = _axes(mask, frame_shape)
    if parts is None:
        return {}
    ys, _, _, major, minor = parts
    return {
        "elongation": float(np.sqrt(major / max(minor, 1e-12))),
        "centroid_y": float(ys.mean() / max(float(frame_shape[0]), 1.0)),
    }


def combine_modes(probabilities: Mapping[str, float]) -> float:
    """Combine per-mode probabilities into one evidence value, by max.

    Each mode is a detector for one fall posture, so a fall is evidenced when
    any of them fires. Adding a mode can only raise the result, which is why a
    new one has to catch falls the others miss faster than it raises false
    positives.
    """
    if not probabilities:
        raise ValueError("combine_modes needs at least one mode")
    return float(max(probabilities.values()))


def window_score(history: Sequence[float]) -> float | None:
    """Median of the recent evidence, or `None` with no history at all.

    The median needs a majority of the window to move, so one dropped or
    broken mask cannot decide, and a pose held only briefly -- bending to pick
    something up -- never carries it. How long a fall must persist is not
    decided here: that stays in the robot's fall state machine.
    """
    import numpy as np

    if len(history) == 0:
        return None
    return float(np.median(np.asarray(history, dtype=float)))
