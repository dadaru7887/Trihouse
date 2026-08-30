import pytest

from vision_ai.robot.recovery.completion_runtime import build_completion


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
            "risk_confidence": 0.9, "vlm_uncertainty": 0.1,
        },
    }


def test_actual_action_result_builds_original_reward_and_trainable_tuple() -> None:
    execution = {
        "command_id": "11111111-1111-4111-8111-111111111111",
        "success": True, "status": "succeeded", "terminal": True,
        "clearance_after_m": 0.5, "elapsed_seconds": 1.0,
        "safety_intervened": False,
    }
    next_state = (0.2, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.2)

    completion = build_completion(proposal(), execution, next_state)

    # Original real_reward: progress(0.2) - time(0.1), no clearance/intervention/rejoin.
    assert completion["transition"]["reward"] == pytest.approx(0.1)
    assert completion["transition"]["state"] == [
        0.0, 0.0, 0.0, 1.0, 0.0, 0.5, 0.5, 0.9, 0.1,
    ]
    assert completion["transition"]["next_state"] == list(next_state)
    assert completion["transition"]["meta"]["is_execution"] is True


def test_unobserved_clearance_is_not_silently_written_as_training_data() -> None:
    execution = {
        "command_id": "11111111-1111-4111-8111-111111111111",
        "success": False, "status": "failed", "terminal": True,
        "clearance_after_m": -1.0, "elapsed_seconds": 1.0,
        "safety_intervened": True,
    }

    try:
        build_completion(proposal(), execution, (0.0,) * 9)
    except ValueError as error:
        assert "clearance" in str(error)
    else:
        raise AssertionError("unknown clearance must fail closed")
