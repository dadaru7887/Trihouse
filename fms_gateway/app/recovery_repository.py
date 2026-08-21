"""Atomic recovery completion and learning-transition persistence."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Protocol

from .database import Database
from model.vlm_rl.shared.contracts import SKILL_NAMES, SKILL_TO_ACTION_TYPE


class RecoveryStepNotFound(Exception):
    pass


class RecoveryStepConflict(Exception):
    pass


class RecoveryIdempotencyConflict(Exception):
    pass


class RecoveryRepository(Protocol):
    def complete_recovery_step(self, episode_uuid: str, step_no: int,
                               request: dict[str, Any], message_id: str,
                               payload_sha256: str) -> dict[str, Any]: ...
    def list_training_rows(self) -> list[dict[str, Any]]: ...


class InMemoryRecoveryRepository:
    """Deterministic unit-test adapter with the same idempotency contract."""

    def __init__(self):
        self.steps: dict[tuple[str, int], dict[str, Any]] = {}
        self.receipts: dict[str, tuple[str, dict[str, Any]]] = {}
        self.transitions: dict[tuple[str, int], dict[str, Any]] = {}
        self.training_rows: list[dict[str, Any]] = []

    def list_training_rows(self) -> list[dict[str, Any]]:
        return deepcopy(self.training_rows)

    def add_running_step(self, episode_uuid: str, step_no: int, action_type: str = "rejoin",
                         recovery_step_id: int = 1) -> None:
        self.steps[(episode_uuid, step_no)] = {
            "recovery_step_id": recovery_step_id,
            "action_type": action_type,
            "execution_status": "running",
        }

    def complete_recovery_step(self, episode_uuid: str, step_no: int,
                               request: dict[str, Any], message_id: str,
                               payload_sha256: str) -> dict[str, Any]:
        existing = self.receipts.get(message_id)
        if existing:
            if existing[0] != payload_sha256:
                raise RecoveryIdempotencyConflict
            return deepcopy(existing[1])
        key = (episode_uuid, step_no)
        step = self.steps.get(key)
        if step is None:
            raise RecoveryStepNotFound
        if step["execution_status"] != "running":
            raise RecoveryStepConflict
        transition = request["transition"]
        if step["action_type"] != SKILL_TO_ACTION_TYPE[transition["skill"]]:
            raise RecoveryStepConflict
        response = {
            "message_id": message_id,
            "recovery_step_id": step["recovery_step_id"],
            "execution_status": request["execution_status"],
            "acknowledged": True,
        }
        step["execution_status"] = request["execution_status"]
        self.transitions[key] = deepcopy(transition)
        self.receipts[message_id] = (payload_sha256, deepcopy(response))
        return response


class MySqlRecoveryRepository:
    def __init__(self, database: Database):
        self.database = database

    def complete_recovery_step(self, episode_uuid: str, step_no: int,
                               request: dict[str, Any], message_id: str,
                               payload_sha256: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("USE trihouse_recovery")
            cursor.execute(
                "SELECT payload_sha256, response_payload FROM recovery_ingestion_receipts "
                "WHERE message_id=%s FOR UPDATE", (message_id,),
            )
            receipt = cursor.fetchone()
            if receipt:
                if receipt["payload_sha256"] != payload_sha256:
                    raise RecoveryIdempotencyConflict
                response = receipt["response_payload"]
                return json.loads(response) if isinstance(response, str) else response

            cursor.execute(
                "SELECT recovery_step_id, action_type, execution_status FROM recovery_steps "
                "WHERE recovery_episode_uuid=%s AND step_no=%s FOR UPDATE",
                (episode_uuid, step_no),
            )
            step = cursor.fetchone()
            if step is None:
                raise RecoveryStepNotFound
            if step["execution_status"] != "running":
                raise RecoveryStepConflict
            transition = request["transition"]
            if step["action_type"] != SKILL_TO_ACTION_TYPE[transition["skill"]]:
                raise RecoveryStepConflict

            cursor.execute(
                "UPDATE recovery_steps SET execution_status=%s, outcome_class=%s, "
                "completed_at=%s, is_terminal=%s, reward_components=%s "
                "WHERE recovery_step_id=%s",
                (request["execution_status"], request["outcome_class"],
                 request["completed_at"], int(request["is_terminal"]),
                 json.dumps(request["reward_components"], separators=(",", ":")),
                 step["recovery_step_id"]),
            )
            cursor.execute(
                "INSERT INTO recovery_learning_transitions "
                "(recovery_step_id,schema_version,state_vector,skill_id,skill_name,"
                "action_vector,reward_total,next_state_vector,done,metadata) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (step["recovery_step_id"], transition["schema_version"],
                 json.dumps(transition["state"], separators=(",", ":")),
                 transition["skill"], SKILL_NAMES[transition["skill"]],
                 json.dumps(transition["coord"], separators=(",", ":")),
                 transition["reward"],
                 json.dumps(transition["next_state"], separators=(",", ":")),
                 int(transition["done"]),
                 json.dumps(transition["meta"], separators=(",", ":"))),
            )
            if request["is_terminal"]:
                episode_status = {
                    "succeeded": "succeeded", "failed": "failed", "cancelled": "aborted"
                }[request["execution_status"]]
                cursor.execute(
                    "UPDATE recovery_episodes SET final_status=%s, ended_at=%s "
                    "WHERE recovery_episode_uuid=%s AND final_status='running'",
                    (episode_status, request["completed_at"], episode_uuid),
                )
            response = {
                "message_id": message_id,
                "recovery_step_id": step["recovery_step_id"],
                "execution_status": request["execution_status"],
                "acknowledged": True,
            }
            cursor.execute(
                "INSERT INTO recovery_ingestion_receipts "
                "(message_id,payload_sha256,message_type,resource_key,response_payload) "
                "VALUES (%s,%s,'recovery_step_completion',%s,%s)",
                (message_id, payload_sha256, f"{episode_uuid}:{step_no}",
                 json.dumps(response, separators=(",", ":"))),
            )
            connection.commit()
            cursor.close()
            return response

    def list_training_rows(self) -> list[dict[str, Any]]:
        from .recovery_export import TRAINING_EXPORT_SQL

        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(TRAINING_EXPORT_SQL)
            rows = list(cursor.fetchall())
            cursor.close()
            return rows
