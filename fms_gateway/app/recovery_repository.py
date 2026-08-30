"""Atomic recovery completion and learning-transition persistence."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from typing import Any, Protocol
from uuid import uuid4

from .database import Database
from vision_ai.utils.contracts import (
    RecoveryStateV1,
    SKILL_NAMES,
    SKILL_TO_ACTION_FAMILY,
)
from vision_ai.utils.motion_plan import Pose2D, canonicalize_recovery_action


class RecoveryStepNotFound(Exception):
    pass


class RecoveryStepConflict(Exception):
    pass


class RecoveryIdempotencyConflict(Exception):
    pass


class RecoveryProposalConflict(Exception):
    pass


class RecoveryProposalNotFound(Exception):
    pass


class RecoveryApprovalForbidden(Exception):
    pass


class RecoveryRepository(Protocol):
    def complete_recovery_step(self, episode_uuid: str, step_no: int,
                               request: dict[str, Any], message_id: str,
                               payload_sha256: str) -> dict[str, Any]: ...
    def list_training_rows(self) -> list[dict[str, Any]]: ...
    def create_proposal(self, request: dict[str, Any], message_id: str,
                        payload_sha256: str) -> dict[str, Any]: ...
    def decide_proposal(self, proposal_id: str, worker_id: str,
                        decision: str, reason: str) -> dict[str, Any]: ...
    def list_pending_commands(self) -> list[dict[str, Any]]: ...
    def mark_command_sent(self, command_id: str) -> None: ...
    def record_command_ack(self, robot_id: str, payload: dict[str, Any]) -> None: ...
    def record_execution_result(self, robot_id: str, payload: dict[str, Any]) -> None: ...
    def get_execution_result(self, command_id: str) -> dict[str, Any] | None: ...
    def get_proposal_execution(self, proposal_id: str) -> dict[str, Any]: ...
    def list_open_recoveries(self, device_id: str) -> list[dict[str, Any]]: ...


class InMemoryRecoveryRepository:
    """Deterministic unit-test adapter with the same idempotency contract."""

    def __init__(self, worker_roles: dict[str, str] | None = None):
        self.steps: dict[tuple[str, int], dict[str, Any]] = {}
        self.receipts: dict[str, tuple[str, dict[str, Any]]] = {}
        self.transitions: dict[tuple[str, int], dict[str, Any]] = {}
        self.training_rows: list[dict[str, Any]] = []
        self.worker_roles = dict(worker_roles or {"W-CONTROL-01": "safety_manager"})
        self.proposals: dict[str, dict[str, Any]] = {}
        self.command_outbox: list[dict[str, Any]] = []
        self.execution_results: dict[str, dict[str, Any]] = {}

    def list_pending_commands(self) -> list[dict[str, Any]]:
        return [
            deepcopy(item)
            for item in self.command_outbox
            if item.get("delivery_status", "pending") in {"pending", "sent"}
        ]

    def mark_command_sent(self, command_id: str) -> None:
        for item in self.command_outbox:
            if item["command_id"] == command_id:
                item["delivery_status"] = "sent"
                item["attempt_count"] = item.get("attempt_count", 0) + 1
                return

    def record_command_ack(self, robot_id: str, payload: dict[str, Any]) -> None:
        for item in self.command_outbox:
            if item["command_id"] != payload["command_id"]:
                continue
            if item["device_id"] != robot_id:
                raise RecoveryProposalConflict
            if item["proposal_sha256"] != payload["proposal_sha256"]:
                raise RecoveryProposalConflict
            item["delivery_status"] = (
                "acknowledged" if payload["accepted"] else "failed"
            )
            item["ack_reason_code"] = payload["reason_code"]
            proposal = self.proposals.get(item.get("proposal_id", ""))
            if proposal is not None:
                step = self.steps.get((proposal["recovery_episode_uuid"], proposal["step_no"]))
                if step is not None and step["execution_status"] == "queued":
                    step["execution_status"] = "running" if payload["accepted"] else "failed"
            return
        raise RecoveryProposalNotFound

    def record_execution_result(self, robot_id: str, payload: dict[str, Any]) -> None:
        for item in self.command_outbox:
            if item["command_id"] != payload["command_id"]:
                continue
            if item["device_id"] != robot_id or item["proposal_sha256"] != payload["proposal_sha256"]:
                raise RecoveryProposalConflict
            existing = self.execution_results.get(payload["command_id"])
            if existing is not None and existing != payload:
                raise RecoveryProposalConflict
            self.execution_results[payload["command_id"]] = deepcopy(payload)
            return
        raise RecoveryProposalNotFound

    def get_execution_result(self, command_id: str) -> dict[str, Any] | None:
        result = self.execution_results.get(command_id)
        return deepcopy(result) if result is not None else None

    def get_proposal_execution(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise RecoveryProposalNotFound
        matching = next(
            (item for item in self.command_outbox if item.get("proposal_id") == proposal_id),
            None,
        )
        if matching is None:
            return {"proposal_id": proposal_id, "status": proposal["status"], "result": None}
        return {
            "proposal_id": proposal_id,
            "status": matching.get("delivery_status", "pending"),
            "command_id": matching["command_id"],
            "result": self.get_execution_result(matching["command_id"]),
        }

    def list_open_recoveries(self, device_id: str) -> list[dict[str, Any]]:
        # TRIHOUSE EXTENSION — EN: Recover unfinished Gateway work after a 5080 restart.
        # TRIHOUSE 확장 — KO: 5080 재시작 뒤 Gateway의 미완료 작업을 다시 찾는다.
        rows = []
        for proposal_id, proposal in self.proposals.items():
            if proposal["device_id"] != device_id or proposal["status"] not in {"pending", "approved"}:
                continue
            key = (proposal["recovery_episode_uuid"], proposal["step_no"])
            if key in self.transitions:
                continue
            execution = self.get_proposal_execution(proposal_id)
            if execution["status"] == "failed":
                continue
            rows.append({"proposal": {
                name: deepcopy(proposal[name]) for name in (
                    "proposal_id", "recovery_episode_uuid", "step_no", "device_id",
                    "map_name", "map_revision", "state_schema_id", "state",
                    "selected_skill_id", "selected_skill_name", "selected_coord",
                )
            }, "execution": execution})
        return rows

    def list_training_rows(self) -> list[dict[str, Any]]:
        return deepcopy(self.training_rows)

    def add_running_step(self, episode_uuid: str, step_no: int, action_type: str = "rejoin",
                         recovery_step_id: int = 1) -> None:
        self.steps[(episode_uuid, step_no)] = {
            "recovery_step_id": recovery_step_id,
            "action_type": action_type,
            "execution_status": "running",
        }

    @staticmethod
    def _proposal_hash(value: dict[str, Any]) -> str:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def create_proposal(self, request: dict[str, Any], message_id: str,
                        payload_sha256: str) -> dict[str, Any]:
        proposal_id = request["proposal_id"]
        existing = self.proposals.get(proposal_id)
        if existing:
            if existing["request_sha256"] != payload_sha256:
                raise RecoveryProposalConflict
            return deepcopy(existing["response"])

        state = RecoveryStateV1(**request["state"])
        action = canonicalize_recovery_action(
            request["selected_skill_id"],
            tuple(request["selected_coord"]),
            Pose2D(state.robot_x_m, state.robot_y_m, state.robot_yaw_rad),
        )
        canonical_action = asdict(action)
        proposal_body = deepcopy(request)
        proposal_body["canonical_action"] = canonical_action
        proposal_sha256 = self._proposal_hash(proposal_body)
        response = {
            "proposal_id": proposal_id,
            "status": "pending",
            "action_family": action.action_family,
            "selected_skill_id": action.skill,
            "selected_skill_name": action.skill_name,
            "canonical_action": canonical_action,
            "proposal_sha256": proposal_sha256,
        }
        self.proposals[proposal_id] = {
            **proposal_body,
            "request_sha256": payload_sha256,
            "message_id": message_id,
            "proposal_sha256": proposal_sha256,
            "status": "pending",
            "response": deepcopy(response),
            "decision": None,
        }
        return response

    def decide_proposal(self, proposal_id: str, worker_id: str,
                        decision: str, reason: str) -> dict[str, Any]:
        if self.worker_roles.get(worker_id) != "safety_manager":
            raise RecoveryApprovalForbidden
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise RecoveryProposalNotFound
        requested = {"worker_id": worker_id, "decision": decision, "reason": reason}
        if proposal["decision"] is not None:
            if proposal["decision"]["request"] != requested:
                raise RecoveryProposalConflict
            return deepcopy(proposal["decision"]["response"])

        response: dict[str, Any] = {
            "proposal_id": proposal_id,
            "status": decision,
            "proposal_sha256": proposal["proposal_sha256"],
            "worker_id": worker_id,
        }
        if decision == "approved":
            command = {
                "type": "recovery_command",
                "schema_version": 1,
                "command_id": str(uuid4()),
                "proposal_id": proposal_id,
                "proposal_sha256": proposal["proposal_sha256"],
                "approval_worker_id": worker_id,
                "device_id": proposal["device_id"],
                "map_name": proposal["map_name"],
                "map_revision": proposal["map_revision"],
                "recovery_episode_uuid": proposal["recovery_episode_uuid"],
                "step_no": proposal["step_no"],
                "selected_skill_id": proposal["selected_skill_id"],
                "selected_skill_name": proposal["selected_skill_name"],
                "canonical_action": proposal["canonical_action"],
            }
            self.command_outbox.append({**deepcopy(command), "payload": deepcopy(command)})
            self.steps[(proposal["recovery_episode_uuid"], proposal["step_no"])] = {
                "recovery_step_id": len(self.steps) + 1,
                "action_type": proposal["canonical_action"]["action_family"],
                "execution_status": "queued",
            }
            response["command"] = command
        proposal["status"] = decision
        proposal["decision"] = {"request": requested, "response": deepcopy(response)}
        return response

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
        if step["action_type"] != SKILL_TO_ACTION_FAMILY[transition["skill"]]:
            raise RecoveryStepConflict
        response = {
            "message_id": message_id,
            "recovery_step_id": step["recovery_step_id"],
            "execution_status": request["execution_status"],
            "acknowledged": True,
        }
        step["execution_status"] = request["execution_status"]
        self.transitions[key] = deepcopy(transition)
        proposal = next(
            (
                value for value in self.proposals.values()
                if value["recovery_episode_uuid"] == episode_uuid
                and value["step_no"] == step_no
            ),
            {},
        )
        self.training_rows.append({
            "recovery_episode_uuid": episode_uuid,
            "device_id": proposal.get("device_id", "unknown"),
            "map_name": proposal.get("map_name", "unknown"),
            "map_revision": proposal.get("map_revision", "unknown"),
            "vlm_model_name": proposal.get("vlm_lineage", {}).get("model"),
            "vlm_model_version": proposal.get("vlm_lineage", {}).get("revision"),
            "recovery_policy_name": proposal.get("policy_lineage", {}).get("model", "unknown"),
            "recovery_policy_version": proposal.get("policy_lineage", {}).get(
                "checkpoint_sha256", "unknown"
            ),
            "step_no": step_no,
            "outcome_class": request["outcome_class"],
            "execution_status": request["execution_status"],
            "state_vector": transition["state"],
            "skill_id": transition["skill"],
            "action_vector": transition["coord"],
            "reward_total": transition["reward"],
            "next_state_vector": transition["next_state"],
            "done": transition["done"],
            "metadata": transition["meta"],
        })
        self.receipts[message_id] = (payload_sha256, deepcopy(response))
        return response


class MySqlRecoveryRepository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _json_value(value: Any) -> Any:
        return json.loads(value) if isinstance(value, str) else value

    @staticmethod
    def _optional_json(value: Any) -> str | None:
        """Store an absent selector verdict as SQL NULL, not as a JSON null."""
        return None if value is None else json.dumps(value, separators=(",", ":"))

    def list_pending_commands(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("USE trihouse_recovery")
            cursor.execute(
                "SELECT command_id,device_id,payload FROM recovery_command_outbox "
                "WHERE delivery_status IN ('pending','sent') AND next_attempt_at <= NOW(6) "
                "ORDER BY created_at LIMIT 50"
            )
            rows = [
                {
                    "command_id": row["command_id"],
                    "device_id": row["device_id"],
                    "payload": self._json_value(row["payload"]),
                }
                for row in cursor.fetchall()
            ]
            cursor.close()
            return rows

    def mark_command_sent(self, command_id: str) -> None:
        with self.database.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("USE trihouse_recovery")
            cursor.execute(
                "UPDATE recovery_command_outbox SET delivery_status='sent', "
                "attempt_count=attempt_count+1,delivered_at=NOW(6),"
                "next_attempt_at=DATE_ADD(NOW(6), INTERVAL 2 SECOND) "
                "WHERE command_id=%s AND delivery_status IN ('pending','sent')",
                (command_id,),
            )
            connection.commit()
            cursor.close()

    def record_command_ack(self, robot_id: str, payload: dict[str, Any]) -> None:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("USE trihouse_recovery")
            cursor.execute(
                "SELECT proposal_id,device_id,payload FROM recovery_command_outbox "
                "WHERE command_id=%s FOR UPDATE", (payload["command_id"],),
            )
            command = cursor.fetchone()
            if command is None:
                raise RecoveryProposalNotFound
            command_payload = self._json_value(command["payload"])
            if (
                command["device_id"] != robot_id
                or command_payload["proposal_sha256"] != payload["proposal_sha256"]
            ):
                raise RecoveryProposalConflict
            status = "acknowledged" if payload["accepted"] else "failed"
            cursor.execute(
                "UPDATE recovery_command_outbox SET delivery_status=%s,"
                "acknowledged_at=NOW(6),last_error=%s WHERE command_id=%s",
                (status, None if payload["accepted"] else payload["reason_code"],
                 payload["command_id"]),
            )
            cursor.execute(
                "UPDATE recovery_steps s JOIN recovery_proposals p "
                "ON p.recovery_episode_uuid=s.recovery_episode_uuid AND p.step_no=s.step_no "
                "SET s.execution_status=%s WHERE p.proposal_id=%s "
                "AND s.execution_status='queued'",
                ("running" if payload["accepted"] else "failed", command["proposal_id"]),
            )
            connection.commit()
            cursor.close()

    def record_execution_result(self, robot_id: str, payload: dict[str, Any]) -> None:
        result_sha256 = InMemoryRecoveryRepository._proposal_hash(payload)
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("USE trihouse_recovery")
            cursor.execute(
                "SELECT device_id,payload FROM recovery_command_outbox "
                "WHERE command_id=%s FOR UPDATE", (payload["command_id"],),
            )
            command = cursor.fetchone()
            if command is None:
                raise RecoveryProposalNotFound
            command_payload = self._json_value(command["payload"])
            if (
                command["device_id"] != robot_id
                or command_payload["proposal_sha256"] != payload["proposal_sha256"]
            ):
                raise RecoveryProposalConflict
            cursor.execute(
                "SELECT result_sha256 FROM recovery_execution_results "
                "WHERE command_id=%s FOR UPDATE", (payload["command_id"],),
            )
            existing = cursor.fetchone()
            if existing is not None:
                if existing["result_sha256"] != result_sha256:
                    raise RecoveryProposalConflict
                return
            cursor.execute(
                "INSERT INTO recovery_execution_results "
                "(command_id,device_id,proposal_sha256,execution_status,success,result_payload,result_sha256) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (payload["command_id"], robot_id, payload["proposal_sha256"],
                 payload["status"], int(payload["success"]),
                 json.dumps(payload, separators=(",", ":")), result_sha256),
            )
            connection.commit()
            cursor.close()

    def get_execution_result(self, command_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("USE trihouse_recovery")
            cursor.execute(
                "SELECT result_payload FROM recovery_execution_results WHERE command_id=%s",
                (command_id,),
            )
            row = cursor.fetchone()
            cursor.close()
            return self._json_value(row["result_payload"]) if row else None

    def get_proposal_execution(self, proposal_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("USE trihouse_recovery")
            cursor.execute(
                "SELECT p.status AS proposal_status,o.command_id,o.delivery_status,r.result_payload "
                "FROM recovery_proposals p "
                "LEFT JOIN recovery_command_outbox o ON o.proposal_id=p.proposal_id "
                "LEFT JOIN recovery_execution_results r ON r.command_id=o.command_id "
                "WHERE p.proposal_id=%s", (proposal_id,),
            )
            row = cursor.fetchone()
            cursor.close()
            if row is None:
                raise RecoveryProposalNotFound
            return {
                "proposal_id": proposal_id,
                "status": row["delivery_status"] or row["proposal_status"],
                "command_id": row["command_id"],
                "result": self._json_value(row["result_payload"]) if row["result_payload"] else None,
            }

    def list_open_recoveries(self, device_id: str) -> list[dict[str, Any]]:
        # TRIHOUSE EXTENSION — EN: DB-backed restart recovery; not model logic.
        # TRIHOUSE 확장 — KO: 모델 로직이 아닌 DB 기반 재시작 복구 기능이다.
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("USE trihouse_recovery")
            cursor.execute(
                "SELECT p.proposal_id,p.recovery_episode_uuid,p.step_no,p.device_id,"
                "p.map_name,p.map_revision,p.state_schema_id,p.named_state,"
                "p.selected_skill_id,p.selected_skill_name,p.selected_coord,"
                "p.status AS proposal_status,o.command_id,o.delivery_status,r.result_payload "
                "FROM recovery_proposals p "
                "LEFT JOIN recovery_command_outbox o ON o.proposal_id=p.proposal_id "
                "LEFT JOIN recovery_execution_results r ON r.command_id=o.command_id "
                "LEFT JOIN recovery_steps s ON s.recovery_episode_uuid=p.recovery_episode_uuid "
                "AND s.step_no=p.step_no "
                "LEFT JOIN recovery_learning_transitions t ON t.recovery_step_id=s.recovery_step_id "
                "WHERE p.device_id=%s AND p.status IN ('pending','approved') "
                "AND t.recovery_step_id IS NULL "
                "AND (o.delivery_status IS NULL OR o.delivery_status <> 'failed') "
                "ORDER BY p.created_at LIMIT 10",
                (device_id,),
            )
            rows = []
            for row in cursor.fetchall():
                proposal = {
                    "proposal_id": row["proposal_id"],
                    "recovery_episode_uuid": row["recovery_episode_uuid"],
                    "step_no": row["step_no"],
                    "device_id": row["device_id"],
                    "map_name": row["map_name"],
                    "map_revision": row["map_revision"],
                    "state_schema_id": row["state_schema_id"],
                    "state": self._json_value(row["named_state"]),
                    "selected_skill_id": row["selected_skill_id"],
                    "selected_skill_name": row["selected_skill_name"],
                    "selected_coord": self._json_value(row["selected_coord"]),
                }
                rows.append({
                    "proposal": proposal,
                    "execution": {
                        "proposal_id": row["proposal_id"],
                        "status": row["delivery_status"] or row["proposal_status"],
                        "command_id": row["command_id"],
                        "result": self._json_value(row["result_payload"])
                        if row["result_payload"] else None,
                    },
                })
            cursor.close()
            return rows

    def create_proposal(self, request: dict[str, Any], message_id: str,
                        payload_sha256: str) -> dict[str, Any]:
        state = RecoveryStateV1(**request["state"])
        action = canonicalize_recovery_action(
            request["selected_skill_id"],
            tuple(request["selected_coord"]),
            Pose2D(state.robot_x_m, state.robot_y_m, state.robot_yaw_rad),
        )
        canonical_action = asdict(action)
        proposal_body = deepcopy(request)
        proposal_body["canonical_action"] = canonical_action
        proposal_sha256 = InMemoryRecoveryRepository._proposal_hash(proposal_body)
        response = {
            "proposal_id": request["proposal_id"],
            "status": "pending",
            "action_family": action.action_family,
            "selected_skill_id": action.skill,
            "selected_skill_name": action.skill_name,
            "canonical_action": canonical_action,
            "proposal_sha256": proposal_sha256,
        }
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("USE trihouse_recovery")
            cursor.execute(
                "SELECT request_sha256, proposal_sha256, action_family, selected_skill_id, "
                "selected_skill_name, canonical_action, status FROM recovery_proposals "
                "WHERE proposal_id=%s FOR UPDATE",
                (request["proposal_id"],),
            )
            existing = cursor.fetchone()
            if existing:
                if existing["request_sha256"] != payload_sha256:
                    raise RecoveryProposalConflict
                return {
                    "proposal_id": request["proposal_id"],
                    "status": existing["status"],
                    "action_family": existing["action_family"],
                    "selected_skill_id": existing["selected_skill_id"],
                    "selected_skill_name": existing["selected_skill_name"],
                    "canonical_action": self._json_value(existing["canonical_action"]),
                    "proposal_sha256": existing["proposal_sha256"],
                }
            cursor.execute(
                "SELECT active FROM trihouse_fms.devices WHERE device_id=%s FOR SHARE",
                (request["device_id"],),
            )
            device = cursor.fetchone()
            if device is None or not device["active"]:
                raise RecoveryProposalConflict
            vlm = request["vlm_lineage"]
            policy = request["policy_lineage"]
            cursor.execute(
                "INSERT INTO recovery_episodes "
                "(recovery_episode_uuid,device_id,map_name,map_revision,trigger_type,"
                "vlm_model_name,vlm_model_version,recovery_policy_name,"
                "recovery_policy_version,started_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(6))",
                (request["recovery_episode_uuid"], request["device_id"], request["map_name"],
                 request["map_revision"], request["trigger_type"], vlm.get("model"),
                 vlm.get("revision"), policy.get("model", "TGRPO+SAC"),
                 policy.get("checkpoint_sha256", "unknown")),
            )
            cursor.execute(
                "INSERT INTO recovery_proposals "
                "(proposal_id,recovery_episode_uuid,step_no,device_id,map_name,map_revision,"
                "trigger_type,state_schema_id,named_state,perception_evidence,vlm_lineage,"
                "policy_lineage,candidate_evidence,skill_selection,selected_skill_id,selected_skill_name,"
                "action_family,selected_coord,canonical_action,safety_gate_enabled,"
                "request_sha256,proposal_sha256) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (request["proposal_id"], request["recovery_episode_uuid"], request["step_no"],
                 request["device_id"], request["map_name"], request["map_revision"],
                 request["trigger_type"], request["state_schema_id"],
                 json.dumps(request["state"], separators=(",", ":")),
                 json.dumps(request["perception_evidence"], separators=(",", ":")),
                 json.dumps(vlm, separators=(",", ":")),
                 json.dumps(policy, separators=(",", ":")),
                 json.dumps(request.get("candidate_evidence", []), separators=(",", ":")),
                 self._optional_json(request.get("skill_selection")),
                 action.skill, action.skill_name,
                 action.action_family, json.dumps(request["selected_coord"], separators=(",", ":")),
                 json.dumps(canonical_action, separators=(",", ":")), int(request["safety_gate_enabled"]),
                 payload_sha256, proposal_sha256),
            )
            connection.commit()
            cursor.close()
            return response

    def decide_proposal(self, proposal_id: str, worker_id: str,
                        decision: str, reason: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("USE trihouse_recovery")
            cursor.execute(
                "SELECT role,active FROM trihouse_fms.workers WHERE worker_id=%s FOR SHARE",
                (worker_id,),
            )
            worker = cursor.fetchone()
            if worker is None or not worker["active"] or worker["role"] != "safety_manager":
                raise RecoveryApprovalForbidden
            cursor.execute(
                "SELECT * FROM recovery_proposals WHERE proposal_id=%s FOR UPDATE",
                (proposal_id,),
            )
            proposal = cursor.fetchone()
            if proposal is None:
                raise RecoveryProposalNotFound
            cursor.execute(
                "SELECT approval_id,worker_id,decision,reason FROM recovery_approval_decisions "
                "WHERE proposal_id=%s FOR UPDATE", (proposal_id,),
            )
            existing = cursor.fetchone()
            if existing:
                if (existing["worker_id"], existing["decision"], existing["reason"]) != (
                    worker_id, decision, reason
                ):
                    raise RecoveryProposalConflict
                response = {
                    "proposal_id": proposal_id,
                    "status": decision,
                    "proposal_sha256": proposal["proposal_sha256"],
                    "worker_id": worker_id,
                }
                if decision == "approved":
                    cursor.execute(
                        "SELECT payload FROM recovery_command_outbox WHERE proposal_id=%s",
                        (proposal_id,),
                    )
                    response["command"] = self._json_value(cursor.fetchone()["payload"])
                return response

            approval_id = str(uuid4())
            cursor.execute(
                "INSERT INTO recovery_approval_decisions "
                "(approval_id,proposal_id,worker_id,decision,reason,proposal_sha256) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (approval_id, proposal_id, worker_id, decision, reason, proposal["proposal_sha256"]),
            )
            cursor.execute(
                "UPDATE recovery_proposals SET status=%s,decided_at=NOW(6) WHERE proposal_id=%s",
                (decision, proposal_id),
            )
            response: dict[str, Any] = {
                "proposal_id": proposal_id,
                "status": decision,
                "proposal_sha256": proposal["proposal_sha256"],
                "worker_id": worker_id,
            }
            if decision == "approved":
                canonical_action = self._json_value(proposal["canonical_action"])
                cursor.execute(
                    "INSERT INTO recovery_steps "
                    "(recovery_episode_uuid,step_no,action_type,target_pose,outcome_class,"
                    "execution_status,started_at) VALUES (%s,%s,%s,%s,'boundary','queued',NOW(6))",
                    (proposal["recovery_episode_uuid"], proposal["step_no"],
                     proposal["action_family"], json.dumps(canonical_action, separators=(",", ":"))),
                )
                command = {
                    "type": "recovery_command",
                    "schema_version": 1,
                    "command_id": str(uuid4()),
                    "proposal_id": proposal_id,
                    "proposal_sha256": proposal["proposal_sha256"],
                    "approval_id": approval_id,
                    "approval_worker_id": worker_id,
                    "device_id": proposal["device_id"],
                    "map_name": proposal["map_name"],
                    "map_revision": proposal["map_revision"],
                    "recovery_episode_uuid": proposal["recovery_episode_uuid"],
                    "step_no": proposal["step_no"],
                    "selected_skill_id": proposal["selected_skill_id"],
                    "selected_skill_name": proposal["selected_skill_name"],
                    "canonical_action": canonical_action,
                }
                payload_sha256 = InMemoryRecoveryRepository._proposal_hash(command)
                cursor.execute(
                    "INSERT INTO recovery_command_outbox "
                    "(command_id,proposal_id,approval_id,device_id,payload,payload_sha256) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (command["command_id"], proposal_id, approval_id, proposal["device_id"],
                     json.dumps(command, separators=(",", ":")), payload_sha256),
                )
                response["command"] = command
            connection.commit()
            cursor.close()
            return response

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
            if step["action_type"] != SKILL_TO_ACTION_FAMILY[transition["skill"]]:
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
