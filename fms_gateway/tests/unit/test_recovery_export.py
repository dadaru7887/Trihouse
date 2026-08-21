import json

from fms_gateway.app.recovery_export import iter_training_jsonl
from model.vlm_rl.shared.contracts import SKILL_NAMES


def test_export_contains_exact_trainer_fields_and_lineage() -> None:
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
    exported = json.loads(next(iter_training_jsonl([row])))
    assert set(exported) == {"state", "skill", "coord", "reward", "next_state", "done", "meta"}
    assert exported["meta"]["device_id"] == "PK_01"
    assert SKILL_NAMES[exported["skill"]] == "REJOIN"
