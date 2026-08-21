"""Convert finalized DB joins to the original offline trainer JSONL shape."""

from __future__ import annotations

import json
from typing import Any, Iterable, Iterator


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def training_record(row: dict[str, Any]) -> dict[str, Any]:
    """Project one terminal executed row without inventing missing model state."""
    meta = _json(row["metadata"])
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
        "outcome_class": row["outcome_class"],
        "execution_status": row["execution_status"],
        "is_execution": True,
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


TRAINING_EXPORT_SQL = """
SELECT e.recovery_episode_uuid, e.device_id, e.map_name, e.map_revision,
       e.vlm_model_name, e.vlm_model_version,
       e.recovery_policy_name, e.recovery_policy_version,
       s.step_no, s.outcome_class, s.execution_status,
       t.state_vector, t.skill_id, t.action_vector, t.reward_total,
       t.next_state_vector, t.done, t.metadata
FROM trihouse_recovery.recovery_episodes e
JOIN trihouse_recovery.recovery_steps s
  ON s.recovery_episode_uuid = e.recovery_episode_uuid
JOIN trihouse_recovery.recovery_learning_transitions t
  ON t.recovery_step_id = s.recovery_step_id
WHERE e.final_status <> 'running'
  AND s.execution_status IN ('succeeded','failed','cancelled')
  AND JSON_EXTRACT(t.metadata, '$.is_execution') = TRUE
ORDER BY e.started_at, e.recovery_episode_uuid, s.step_no
""".strip()
