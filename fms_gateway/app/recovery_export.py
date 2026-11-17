"""Convert finalized DB joins to the original offline trainer JSONL shape."""

from __future__ import annotations

import json
from typing import Any, Iterable, Iterator


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _epoch_seconds(value: Any) -> float:
    """Convert the DB completion time to the float clock the sampler decays on.

    A missing time must not silently become "now": the sampler weights recency as
    ``exp(-age/3600)``, so a wrong-but-recent stamp would over-sample an old row.
    0.0 keeps such a row at the oldest end instead.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    timestamp = getattr(value, "timestamp", None)
    return float(timestamp()) if callable(timestamp) else 0.0


def training_record(row: dict[str, Any]) -> dict[str, Any]:
    """Project one terminal executed row without inventing missing model state."""
    meta = _json(row["metadata"])
    outcome_class = row["outcome_class"]
    lineage = {
        "episode_uuid": row["recovery_episode_uuid"],
        "step_no": row["step_no"],
        "device_id": row["device_id"],
        "map_name": row["map_name"],
        "map_revision": row["map_revision"],
        "vlm_model_name": row.get("vlm_model_name"),
        "vlm_model_version": row.get("vlm_model_version"),
        "recovery_policy_name": row["recovery_policy_name"],
        "recovery_policy_version": row["recovery_policy_version"],
        "outcome_class": outcome_class,
        "execution_status": row["execution_status"],
        "is_execution": True,
        # EN: The three keys below are the names the offline replay sampler reads.
        # Without them every row lands in one bucket with a constant weight, so the
        # risk-stratified ratio silently degrades into a reward threshold.
        # KO: 아래 세 키가 오프라인 replay sampler 가 읽는 이름이다. 없으면 모든
        # 행이 한 버킷에 상수 가중치로 들어가, 위험도 층화가 reward 임계값 하나로
        # 조용히 퇴화한다.
        "terminal_critical": outcome_class == "critical",
        "timestamp": _epoch_seconds(row.get("completed_at")),
        "map_zone": row.get("map_zone") or row["map_name"],
    }
    return {
        "state": _json(row["state_vector"]),
        "skill": row["skill_id"],
        "coord": _json(row["action_vector"]),
        "reward": row["reward_total"],
        "next_state": _json(row["next_state_vector"]),
        "done": bool(row["done"]),
        "meta": {**meta, **lineage},
    }


def iter_training_jsonl(rows: Iterable[dict[str, Any]]) -> Iterator[str]:
    for row in rows:
        yield json.dumps(training_record(row), sort_keys=True, separators=(",", ":")) + "\n"


# EN: `completed_at` and the temperature zone already exist in the operational
#     schema; they are joined here so the sampler never has to invent them.
#     The zone join is LEFT because a recovery may run outside a job step.
# KO: `completed_at` 과 온도 구역은 이미 운영 스키마에 있다. sampler 가 지어내지
#     않도록 여기서 함께 뽑는다. 작업 스텝 밖에서 일어난 복구도 있으므로 구역
#     조인은 LEFT 다.
TRAINING_EXPORT_SQL = """
SELECT e.recovery_episode_uuid, e.device_id, e.map_name, e.map_revision,
       e.vlm_model_name, e.vlm_model_version,
       e.recovery_policy_name, e.recovery_policy_version,
       s.step_no, s.outcome_class, s.execution_status, s.completed_at,
       COALESCE(l.temperature_zone, l.zone_code) AS map_zone,
       t.state_vector, t.skill_id, t.action_vector, t.reward_total,
       t.next_state_vector, t.done, t.metadata
FROM trihouse_recovery.recovery_episodes e
JOIN trihouse_recovery.recovery_steps s
  ON s.recovery_episode_uuid = e.recovery_episode_uuid
JOIN trihouse_recovery.recovery_learning_transitions t
  ON t.recovery_step_id = s.recovery_step_id
LEFT JOIN trihouse_fms.job_steps js
  ON js.job_step_id = e.fms_job_step_id
LEFT JOIN trihouse_fms.locations l
  ON l.location_id = js.target_location_id
WHERE e.final_status <> 'running'
  AND s.execution_status IN ('succeeded','failed','cancelled')
  AND JSON_EXTRACT(t.metadata, '$.is_execution') = TRUE
ORDER BY e.started_at, e.recovery_episode_uuid, s.step_no
""".strip()
