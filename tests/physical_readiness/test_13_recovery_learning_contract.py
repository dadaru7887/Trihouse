import json

from fms_gateway.app.recovery_export import iter_training_jsonl
from vision_ai.data_loader.recovery.dataset import load_training_jsonl


def test_database_export_round_trips_all_six_learning_fields(tmp_path) -> None:
    row = {
        "recovery_episode_uuid": "episode-1", "device_id": "PK_01",
        "map_name": "new_map_2", "map_revision": "rev-1",
        "vlm_model_name": "vlm", "vlm_model_version": "1",
        "recovery_policy_name": "tgrpo-sac", "recovery_policy_version": "1",
        "step_no": 1, "outcome_class": "safe", "execution_status": "succeeded",
        "state_vector": json.dumps([0.0] * 9), "skill_id": 4,
        "action_vector": json.dumps([0.1, 0.0, 0.0]), "reward_total": 0.2,
        "next_state_vector": json.dumps([0.1] + [0.0] * 8), "done": 1,
        "metadata": json.dumps({"is_execution": True}),
    }
    path = tmp_path / "recovery.jsonl"
    path.write_text("".join(iter_training_jsonl([row])), encoding="utf-8")
    transition = load_training_jsonl(path)[0]
    assert transition.state == tuple([0.0] * 9)
    assert transition.skill == 4
    assert transition.coord == (0.1, 0.0, 0.0)
    assert transition.reward == 0.2
    assert transition.next_state == tuple([0.1] + [0.0] * 8)
    assert transition.done is True
