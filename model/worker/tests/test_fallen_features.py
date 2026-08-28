"""분류기가 학습한 것과 같은 좌표계에서 피처를 잰다."""

import math

import numpy as np
import pytest

from model.perception.segmentation.runtime.detector import Detection

FRAME = (480, 640)  # (height, width) — deliberately not square


def mask_at(x: int, y: int, width: int, height: int):
    mask = np.zeros(FRAME, dtype=bool)
    mask[y:y + height, x:x + width] = True
    return mask


def test_aspect_ratio_is_measured_on_normalized_coordinates() -> None:
    """The classifier was trained on masks.xyn, not on pixels.

    aspect_ratio carries the largest coefficient in the bundle, so measuring it
    on the wrong basis quietly corrupts the strongest signal. On a 640x480 frame
    a 200x100 pixel mask is 2.0 in pixels but 1.5 normalized.
    """
    from model.worker.person.features import geometric_features

    aspect, _, _ = geometric_features(mask_at(0, 0, 200, 100), FRAME)

    assert aspect == pytest.approx(1.5, abs=1e-6)


def test_centroid_y_is_the_normalized_vertical_position() -> None:
    from model.worker.person.features import geometric_features

    _, _, low = geometric_features(mask_at(0, 360, 100, 100), FRAME)
    _, _, high = geometric_features(mask_at(0, 0, 100, 100), FRAME)

    assert low > high
    assert 0.0 <= high <= 1.0 and 0.0 <= low <= 1.0


def test_pca_angle_reads_the_principal_axis_of_the_mask() -> None:
    """A lying person's mask is elongated horizontally, a standing one vertically."""
    from model.worker.person.features import geometric_features

    _, lying_angle, _ = geometric_features(mask_at(100, 200, 300, 20), FRAME)
    _, standing_angle, _ = geometric_features(mask_at(300, 100, 20, 300), FRAME)

    assert lying_angle == pytest.approx(0.0, abs=5.0)
    assert standing_angle == pytest.approx(90.0, abs=5.0)


def test_pca_angle_stays_within_a_half_turn() -> None:
    from model.worker.person.features import geometric_features

    for x in (0, 50, 200):
        _, angle, _ = geometric_features(mask_at(x, 100, 200, 40), FRAME)
        assert 0.0 <= angle < 180.0


def test_an_empty_mask_has_no_features() -> None:
    from model.worker.person.features import geometric_features

    assert geometric_features(np.zeros(FRAME, dtype=bool), FRAME) is None


def test_contact_separates_people_from_obstacles() -> None:
    from model.worker.person.features import contact_features

    target = Detection(1, 0.9, mask_at(100, 100, 100, 100), "a")
    overlapping_person = Detection(1, 0.9, mask_at(150, 100, 100, 100), "b")
    distant_obstacle = Detection(0, 0.9, mask_at(400, 400, 50, 50), "c")

    person_iou, obstacle_iou = contact_features(
        target, [target, overlapping_person, distant_obstacle], person_class_id=1
    )

    assert person_iou > 0.0
    assert obstacle_iou == 0.0


def test_contact_reports_the_obstacle_a_person_leans_on() -> None:
    from model.worker.person.features import contact_features

    target = Detection(1, 0.9, mask_at(100, 100, 100, 100), "a")
    shelf = Detection(0, 0.9, mask_at(150, 100, 100, 100), "c")

    person_iou, obstacle_iou = contact_features(target, [target, shelf], person_class_id=1)

    assert person_iou == 0.0
    assert obstacle_iou > 0.0


def test_a_detection_does_not_count_as_touching_itself() -> None:
    """Upstream drops anything overlapping at IoU >= 0.95 as the target itself."""
    from model.worker.person.features import contact_features

    target = Detection(1, 0.9, mask_at(100, 100, 100, 100), "a")
    near_duplicate = Detection(1, 0.9, mask_at(101, 100, 100, 100), "b")

    person_iou, _ = contact_features(target, [target, near_duplicate], person_class_id=1)

    assert person_iou == 0.0
