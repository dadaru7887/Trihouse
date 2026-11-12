"""The fall feature contract and how the per-mode evidence is combined.

    pytest vision_ai/tests/worker/test_fallen_features_v2.py

Each test pins something measured on the pinky dataset, not a preference:
an angle a linear model could not use, a combination that diluted one mode's
evidence with another's, and a window that has to survive a dropped frame.
"""

from __future__ import annotations

import numpy as np
import pytest

from vision_ai.models.perception.features import (
    FEATURE_NAMES, combine_modes, diagnostic_features, geometric_features,
    window_score,
)

FRAME = (480, 640)


def _bar(degrees, thickness=12, length=120):
    """A thin bar through the frame centre at `degrees` from horizontal."""
    height, width = FRAME
    ys, xs = np.mgrid[0:height, 0:width]
    theta = np.radians(degrees)
    dy, dx = ys - height / 2, xs - width / 2
    across = np.abs(-dx * np.sin(theta) + dy * np.cos(theta))
    along = np.abs(dx * np.cos(theta) + dy * np.sin(theta))
    return (across < thickness) & (along < length)


def _box(top, left, height, width):
    mask = np.zeros(FRAME, dtype=bool)
    mask[top:top + height, left:left + width] = True
    return mask


STANDING = _box(100, 300, 300, 60)
FALLEN = _box(350, 200, 60, 300)


# ------------------------------------------------------------- contract --

def test_the_contract_is_two_shape_features():
    """Measured on this dataset: adding a third term to the OR raised false
    positives from 13 to 35 at the same recall."""
    assert FEATURE_NAMES == ("aspect_ratio", "axis_horizontality")


def test_geometric_features_returns_the_contract_in_order():
    values = geometric_features(FALLEN, FRAME)
    assert len(values) == len(FEATURE_NAMES)


def test_an_empty_mask_has_no_features():
    assert geometric_features(np.zeros(FRAME, dtype=bool), FRAME) is None


# -------------------------------------------------------- horizontality --

def test_both_lying_directions_score_the_same():
    """0 and 180 degrees are one direction, but as raw numbers they sit at
    opposite ends, so a linear model can call one end fallen and never both.
    Measured that way the angle scored AUC 0.459; folded to |cos| it is 0.962.
    """
    left = geometric_features(_bar(5.0), FRAME)[1]
    right = geometric_features(_bar(175.0), FRAME)[1]
    assert left == pytest.approx(right, abs=0.05)


def test_horizontality_is_high_lying_and_low_standing():
    assert geometric_features(FALLEN, FRAME)[1] > 0.9
    assert geometric_features(STANDING, FRAME)[1] < 0.1


def test_a_diagonal_body_scores_between_the_two():
    """The case aspect_ratio cannot see: its box squares off at 45 degrees,
    while the axis still separates it from an upright body."""
    aspect, horizontality = geometric_features(_bar(45.0), FRAME)
    upright = geometric_features(_bar(90.0), FRAME)[1]
    lying = geometric_features(_bar(0.0), FRAME)[1]

    assert 0.7 < aspect < 1.4                        # the box says "square"
    assert upright < horizontality < lying           # the axis does not


# ------------------------------------------------------------- combine --

def test_the_modes_are_combined_by_or_not_by_averaging():
    """A weighted sum dilutes a mode the other one cannot see. On this dataset
    OR held 13 false positives where the weighted sum had 25, at equal recall.
    """
    assert combine_modes({"aspect": 0.45, "horiz": 0.85}) == pytest.approx(0.85)
    assert combine_modes({"aspect": 0.95, "horiz": 0.10}) == pytest.approx(0.95)


def test_combining_nothing_is_an_error():
    with pytest.raises(ValueError, match="at least one mode"):
        combine_modes({})


def test_adding_a_mode_can_only_raise_the_score():
    """Which is why a new mode has to earn its place: it must catch falls the
    others miss faster than it raises false positives."""
    two = combine_modes({"aspect": 0.4, "horiz": 0.3})
    three = combine_modes({"aspect": 0.4, "horiz": 0.3, "contact": 0.7})
    assert three >= two


# -------------------------------------------------------------- window --

def test_the_window_takes_the_median_not_the_mean():
    """One dropped mask must not move the decision; the mean would follow it."""
    assert window_score([0.9, 0.9, 0.0, 0.9, 0.9]) == pytest.approx(0.9)
    assert window_score([0.9, 0.9, 0.0, 0.9, 0.9]) > np.mean([0.9, 0.9, 0.0, 0.9, 0.9])


def test_a_brief_horizontal_pose_does_not_carry_the_window():
    """Bending to pick something up is horizontal for a moment; a fall is not."""
    assert window_score([0.1, 0.1, 0.9, 0.1, 0.1]) < 0.5


def test_a_short_window_still_returns_a_score():
    """A person just detected has no history yet, and must not be unscoreable."""
    assert window_score([0.8]) == pytest.approx(0.8)


def test_an_empty_window_has_no_score():
    assert window_score([]) is None


# --------------------------------------------------------- diagnostics --

def test_diagnostics_are_reported_but_not_part_of_the_contract():
    """Kept so the removed features can be re-measured on predicted masks
    without changing what the classifier consumes."""
    extra = diagnostic_features(FALLEN, FRAME)
    assert set(extra) == {"elongation", "centroid_y"}
    assert not set(extra) & set(FEATURE_NAMES)
