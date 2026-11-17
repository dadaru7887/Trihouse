from datetime import datetime, timezone
import json

from fms_gateway.app.recovery_export import iter_training_jsonl
from vision_ai.utils.contracts import SKILL_NAMES


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


def training_row(**overrides) -> dict:
    row = {
        "recovery_episode_uuid": "episode-1", "device_id": "PK_01",
        "map_name": "new_map_2", "map_revision": "rev-1",
        "vlm_model_name": "vlm", "vlm_model_version": "1",
        "recovery_policy_name": "tgrpo-sac", "recovery_policy_version": "1",
        "step_no": 1, "outcome_class": "safe", "execution_status": "succeeded",
        "completed_at": datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
        "map_zone": "frozen",
        "state_vector": json.dumps([0.0] * 9), "skill_id": 4,
        "action_vector": json.dumps([0.1, 0.0, 0.0]), "reward_total": 0.2,
        "next_state_vector": json.dumps([0.1] + [0.0] * 8), "done": 1,
        "metadata": json.dumps({"is_execution": True}),
    }
    row.update(overrides)
    return row


def test_export_carries_the_three_names_the_replay_sampler_reads() -> None:
    """이 세 키가 없으면 위험도 층화가 reward 임계값 하나로 조용히 퇴화한다.

    값은 이미 운영 스키마에 있다 — 없던 것은 데이터가 아니라 이름이었다.
    """
    exported = json.loads(next(iter_training_jsonl([training_row()])))

    assert exported["meta"]["terminal_critical"] is False
    assert exported["meta"]["map_zone"] == "frozen"
    assert exported["meta"]["timestamp"] > 0.0


def test_a_critical_outcome_reaches_the_sampler_as_critical() -> None:
    """DB 가 이미 critical 로 판정한 실행이 학습에서 SAFE 로 들어가면 안 된다."""
    exported = json.loads(
        next(iter_training_jsonl([training_row(outcome_class="critical")]))
    )

    assert exported["meta"]["terminal_critical"] is True
    assert exported["meta"]["outcome_class"] == "critical"


def test_a_recovery_outside_a_job_step_still_gets_a_zone_name() -> None:
    """작업 스텝 밖의 복구는 목적지 조인이 비지만, 구역은 여전히 필요하다."""
    exported = json.loads(next(iter_training_jsonl([training_row(map_zone=None)])))

    assert exported["meta"]["map_zone"] == "new_map_2"


def test_a_missing_completion_time_is_not_read_as_now() -> None:
    """recency 가중이 exp(-age/3600) 이라 '지금'으로 읽으면 과대표집된다."""
    exported = json.loads(next(iter_training_jsonl([training_row(completed_at=None)])))

    assert exported["meta"]["timestamp"] == 0.0
