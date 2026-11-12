"""Group A of the fall-feature comparison reproduces the upstream five features.

    pytest vision_ai/tests/worker/test_legacy_features.py

Expected values are worked out by hand from the upstream definitions in
vision_ai/upstream/dev_vision/code/classifier_trainer.py.
"""

import pytest

from vision_ai.models.perception.legacy_features import (
    LEGACY_FEATURE_NAMES, contact_from_boxes, contact_from_instances, legacy_geometric,
)


def rect(x0, y0, x1, y1):
    """A normalised rectangle as a 4-vertex polygon."""
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def test_the_input_order_is_geometric_then_contact():
    assert LEGACY_FEATURE_NAMES == ("aspect_ratio_poly", "pca_angle_deg", "centroid_y",
                                    "contact_person_iou", "contact_obstacle_iou")


def test_geometry_is_measured_on_polygon_vertices():
    aspect, angle, centroid_y = legacy_geometric(rect(0.1, 0.5, 0.5, 0.6))

    assert aspect == pytest.approx(4.0, rel=1e-5)        # 0.4 wide / 0.1 tall
    assert angle == pytest.approx(0.0, abs=1e-3) or angle == pytest.approx(180.0, abs=1e-3)
    assert centroid_y == pytest.approx(0.55, rel=1e-5)   # mean of the four vertex ys


def test_an_upright_polygon_has_a_vertical_axis():
    _, angle, _ = legacy_geometric(rect(0.4, 0.1, 0.45, 0.6))

    assert angle == pytest.approx(90.0, abs=1e-3)


def test_contact_separates_people_from_obstacles():
    target = rect(0.1, 0.1, 0.3, 0.3)
    others = [("Standing", target), ("Fallen", rect(0.2, 0.1, 0.4, 0.3)),
              ("Obstacle", rect(0.7, 0.7, 0.8, 0.8))]

    person, obstacle = contact_from_instances(target, others)

    assert person == pytest.approx(1 / 3, rel=1e-5)     # half overlap of equal boxes
    assert obstacle == 0.0


def test_a_near_duplicate_counts_as_the_target_itself():
    """Upstream drops anything at bbox IoU >= 0.95 as the target."""
    target = rect(0.1, 0.1, 0.3, 0.3)

    person, _ = contact_from_instances(target, [("Standing", rect(0.1, 0.1, 0.301, 0.3))])

    assert person == 0.0


def test_predicted_contact_skips_the_matched_detection_only():
    boxes = [(0.1, 0.1, 0.3, 0.3), (0.1, 0.1, 0.3, 0.3), (0.2, 0.1, 0.4, 0.3)]
    classes = [1, 1, 0]

    person, obstacle = contact_from_boxes(boxes[0], boxes, classes, 0, person_class_id=1)

    assert person == pytest.approx(1.0)                  # an identical other person
    assert obstacle == pytest.approx(1 / 3, rel=1e-5)
