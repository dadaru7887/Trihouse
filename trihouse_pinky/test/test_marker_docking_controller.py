"""ArUco 정렬 뒤 협로에 후진 주차하는 제어 계약."""

import math
import sys
from dataclasses import replace
from pathlib import Path


PINKY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PINKY / "trihouse_pinky_docking"))

from trihouse_pinky_docking.marker_controller import (  # noqa: E402
    ALIGNING,
    COMPLETE,
    REVERSING,
    SEARCHING,
    TURNING,
    DockProfile,
    MarkerDockController,
    MarkerSample,
)


PROFILE = DockProfile(
    marker_id="2",
    minimum_confidence=0.8,
    stable_observations=2,
    observation_timeout_s=0.5,
    standoff_m=0.55,
    distance_tolerance_m=0.03,
    bearing_tolerance_rad=0.04,
    turn_direction=1,
    reverse_distance_m=0.30,
)


def sample(*, received=1.0, marker="2", confidence=0.95, x=0.55, y=0.0):
    return MarkerSample(
        marker_id=marker,
        received_at_s=received,
        ttl_s=0.3,
        confidence=confidence,
        forward_m=x,
        left_m=y,
    )


def test_stale_low_confidence_or_wrong_marker_never_authorizes_motion() -> None:
    controller = MarkerDockController(PROFILE)
    controller.begin(now_s=1.0, pose=(0.0, 0.0, 0.0))

    for observation in (
        sample(received=0.0),
        sample(confidence=0.2),
        sample(marker="1"),
    ):
        controller.observe(observation, now_s=1.0)
        command = controller.advance(now_s=1.0, pose=(0.0, 0.0, 0.0), vision_ready=True)
        assert command.linear_x == 0.0 and command.angular_z == 0.0
        assert controller.state == SEARCHING


def test_marker_must_be_seen_consecutively_before_alignment_moves() -> None:
    controller = MarkerDockController(PROFILE)
    controller.begin(now_s=0.0, pose=(0.0, 0.0, 0.0))

    controller.observe(sample(received=0.0, x=0.80, y=0.20), now_s=0.0)
    assert controller.advance(now_s=0.0, pose=(0.0, 0.0, 0.0), vision_ready=True).linear_x == 0.0
    controller.observe(sample(received=0.1, x=0.80, y=0.20), now_s=0.1)
    command = controller.advance(now_s=0.1, pose=(0.0, 0.0, 0.0), vision_ready=True)

    assert controller.state == ALIGNING
    assert command.angular_z > 0.0


def test_aligned_marker_locks_then_turns_exactly_half_a_turn() -> None:
    controller = MarkerDockController(PROFILE)
    controller.begin(now_s=0.0, pose=(1.0, 2.0, 0.2))
    controller.observe(sample(received=0.0), now_s=0.0)
    controller.observe(sample(received=0.1), now_s=0.1)

    controller.advance(now_s=0.1, pose=(1.0, 2.0, 0.2), vision_ready=True)
    assert controller.state == TURNING
    command = controller.advance(now_s=0.2, pose=(1.0, 2.0, 0.2), vision_ready=True)
    assert command.linear_x == 0.0 and command.angular_z > 0.0

    target_yaw = -math.pi + 0.2
    stopped = controller.advance(
        now_s=0.3, pose=(1.0, 2.0, target_yaw), vision_ready=True
    )
    assert stopped.linear_x == 0.0 and stopped.angular_z == 0.0
    assert controller.state == REVERSING


def test_reverse_holds_heading_without_requiring_marker_and_stops_at_distance() -> None:
    controller = MarkerDockController(PROFILE)
    controller.begin(now_s=0.0, pose=(0.0, 0.0, 0.0))
    controller.observe(sample(received=0.0), now_s=0.0)
    controller.observe(sample(received=0.1), now_s=0.1)
    controller.advance(now_s=0.1, pose=(0.0, 0.0, 0.0), vision_ready=True)
    controller.advance(now_s=0.2, pose=(0.0, 0.0, math.pi), vision_ready=True)

    command = controller.advance(
        now_s=1.5, pose=(0.10, 0.0, math.pi - 0.10), vision_ready=False
    )
    assert controller.state == REVERSING
    assert command.linear_x < 0.0
    assert command.angular_z > 0.0

    stopped = controller.advance(
        now_s=2.0, pose=(0.30, 0.0, math.pi), vision_ready=False
    )
    assert stopped.linear_x == 0.0 and stopped.angular_z == 0.0
    assert controller.state == COMPLETE


def test_losing_readiness_during_marker_alignment_fails_stopped() -> None:
    controller = MarkerDockController(PROFILE)
    controller.begin(now_s=0.0, pose=(0.0, 0.0, 0.0))
    controller.observe(sample(received=0.0, x=0.8), now_s=0.0)
    controller.observe(sample(received=0.1, x=0.8), now_s=0.1)

    command = controller.advance(
        now_s=0.2, pose=(0.0, 0.0, 0.0), vision_ready=False
    )
    assert command.linear_x == 0.0 and command.angular_z == 0.0
    assert controller.is_failed
    assert controller.failure == "vision_not_ready"


def test_external_sensor_loss_aborts_with_a_zero_command() -> None:
    controller = MarkerDockController(PROFILE)
    controller.begin(now_s=0.0, pose=(0.0, 0.0, 0.0))
    command = controller.abort("odom_tf_lost")
    assert command.linear_x == 0.0 and command.angular_z == 0.0
    assert controller.is_failed and controller.failure == "odom_tf_lost"


def test_dock_profile_only_allows_a_goal_inside_its_measured_staging_radius() -> None:
    profile = replace(
        PROFILE,
        activation_x_m=1.0,
        activation_y_m=2.0,
        activation_radius_m=0.20,
    )

    assert profile.allows_activation(1.10, 2.00)
    assert not profile.allows_activation(1.21, 2.00)
