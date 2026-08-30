import math

import pytest

from vision_ai.utils.motion_plan import Pose2D, canonicalize_recovery_action


def test_left_detour_uses_both_dx_and_dy() -> None:
    action = canonicalize_recovery_action(1, (0.1, 0.1, 0.0), Pose2D(0.0, 0.0, 0.0))

    assert action.action_family == "detour"
    assert action.skill_name == "REROUTE_LEFT"
    assert action.heading_rad == pytest.approx(math.pi / 4)
    assert action.distance_m == pytest.approx(math.sqrt(0.02))


def test_detour_rejects_a_direction_that_conflicts_with_the_selected_skill() -> None:
    with pytest.raises(ValueError, match="direction"):
        canonicalize_recovery_action(1, (0.1, -0.1, 0.0), Pose2D(0.0, 0.0, 0.0))


def test_rejoin_converts_relative_coord_to_one_absolute_map_target() -> None:
    action = canonicalize_recovery_action(
        4,
        (0.1, 0.2, 0.3),
        Pose2D(1.0, 2.0, math.pi / 2),
    )

    assert action.map_target == Pose2D(0.8, 2.1, math.pi / 2 + 0.3)
    assert action.coord == pytest.approx((0.1, 0.2, 0.3))


def test_backup_is_bounded_and_canonicalized_to_a_negative_robot_x_offset() -> None:
    action = canonicalize_recovery_action(0, (1.0, 1.0, 0.8), Pose2D(0.0, 0.0, 0.0))

    assert action.coord == pytest.approx((-0.25, 0.0, 0.0))
    assert action.distance_m == pytest.approx(0.25)


def test_wait_discards_policy_coordinate_noise() -> None:
    action = canonicalize_recovery_action(3, (0.2, -0.2, 0.7), Pose2D(0.0, 0.0, 0.0))

    assert action.coord == (0.0, 0.0, 0.0)
    assert action.duration_seconds == 1.0
