import pytest

from vision_ai.robot.recovery.completion_runtime import (
    CLEARANCE_DEFINITION,
    build_completion,
)


def proposal() -> dict:
    return {
        "proposal_id": "22222222-2222-4222-8222-222222222222",
        "recovery_episode_uuid": "44444444-4444-4444-8444-444444444444",
        "step_no": 1,
        "selected_skill_id": 1,
        "selected_skill_name": "REROUTE_LEFT",
        "selected_coord": [0.1, 0.1, 0.0],
        "state": {
            "robot_x_m": 0.0, "robot_y_m": 0.0, "robot_yaw_rad": 0.0,
            "goal_x_m": 1.0, "goal_y_m": 0.0,
            "risk_bbox_center_x_norm": 0.5, "risk_bbox_center_y_norm": 0.5,
            "risk_confidence": 0.9, "scene_confidence": 0.1,
        },
    }


def execution(**overrides) -> dict:
    base = {
        "command_id": "11111111-1111-4111-8111-111111111111",
        "success": True, "status": "succeeded", "terminal": True,
        "clearance_after_m": 0.5, "body_clearance_after_m": 0.5,
        "elapsed_seconds": 1.0, "safety_intervened": False,
    }
    base.update(overrides)
    return base


def test_actual_action_result_builds_original_reward_and_trainable_tuple() -> None:
    next_state = (0.2, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.2)

    completion = build_completion(proposal(), execution(), next_state)

    # Original real_reward: progress(0.2) - time(0.1), no clearance/intervention/rejoin.
    assert completion["transition"]["reward"] == pytest.approx(0.1)
    assert completion["transition"]["state"] == [
        0.0, 0.0, 0.0, 1.0, 0.0, 0.5, 0.5, 0.9, 0.1,
    ]
    assert completion["transition"]["next_state"] == list(next_state)
    assert completion["transition"]["meta"]["is_execution"] is True


def test_transition_records_which_clearance_definition_produced_the_reward() -> None:
    """Two definitions of clearance must never be mixed without a label.

    The measurement changed from an omnidirectional LiDAR minimum to a
    direction-aware body clearance, and the original scans were not kept, so old
    rows cannot be recomputed. Training has to be able to tell them apart.
    """
    completion = build_completion(proposal(), execution(), (0.2,) + (0.0,) * 8)

    assert completion["transition"]["meta"]["clearance_definition"] == CLEARANCE_DEFINITION


def test_side_wall_in_a_narrow_aisle_does_not_read_as_a_collision() -> None:
    """A wall passing 0.10 m to the side is not the robot hitting something.

    The old reward fed one omnidirectional minimum into both the shaping term and
    the terminal check, so travelling down a 0.20 m aisle was charged as danger.
    The path clearance ahead is what the shaping term must see.
    """
    completion = build_completion(
        proposal(),
        execution(clearance_after_m=0.45, body_clearance_after_m=0.04),
        (0.2, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.2),
    )

    assert completion["outcome_class"] == "safe"
    assert completion["reward_components"]["clearance_cost"] == pytest.approx(0.0)


def test_body_contact_is_terminal_even_when_the_path_ahead_is_open() -> None:
    """Collision-grade proximity is true from any direction, not just ahead."""
    completion = build_completion(
        proposal(),
        execution(clearance_after_m=0.90, body_clearance_after_m=0.01),
        (0.2,) + (0.0,) * 8,
    )

    assert completion["transition"]["reward"] == pytest.approx(-100.0)
    assert completion["outcome_class"] == "critical"


@pytest.mark.parametrize(
    "unobserved", [{"clearance_after_m": -1.0}, {"body_clearance_after_m": -1.0}]
)
def test_unobserved_clearance_is_not_silently_written_as_training_data(unobserved) -> None:
    try:
        build_completion(proposal(), execution(**unobserved), (0.0,) * 9)
    except ValueError as error:
        assert "clearance" in str(error)
    else:
        raise AssertionError("unknown clearance must fail closed")
