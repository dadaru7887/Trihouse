from contextlib import contextmanager
import hashlib
import json

import pytest

from conftest import mysql_connection
from fms_gateway.app.recovery_models import RecoveryProposalCreate
from fms_gateway.app.recovery_repository import MySqlRecoveryRepository
from fms_gateway.tests.unit.test_recovery_approval_api import proposal_payload
from vision_ai.robot.recovery.completion_runtime import build_completion


pytestmark = pytest.mark.integration


class TestDatabase:
    @contextmanager
    def connection(self):
        connection = mysql_connection(database="trihouse_fms")
        try:
            yield connection
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()


def test_approval_persists_one_device_routed_command(seeded_schema, recovery_mysql_db):
    repository = MySqlRecoveryRepository(TestDatabase())
    request = RecoveryProposalCreate.model_validate(proposal_payload()).model_dump(mode="json")

    created = repository.create_proposal(request, "11111111-1111-4111-8111-111111111111", "a" * 64)
    approved = repository.decide_proposal(
        request["proposal_id"], "W-CONTROL-01", "approved", "path clear"
    )
    repeated = repository.decide_proposal(
        request["proposal_id"], "W-CONTROL-01", "approved", "path clear"
    )

    assert repeated == approved
    assert approved["proposal_sha256"] == created["proposal_sha256"]
    row = recovery_mysql_db.one(
        "SELECT device_id, delivery_status, payload FROM recovery_command_outbox"
    )
    assert row["device_id"] == "PK_01"
    assert row["delivery_status"] == "pending"
    payload = row["payload"]
    if isinstance(payload, str):
        import json

        payload = json.loads(payload)
    assert payload["selected_skill_name"] == "REROUTE_LEFT"


def test_ack_and_execution_result_are_idempotently_bound_to_the_command(
    seeded_schema, recovery_mysql_db
):
    repository = MySqlRecoveryRepository(TestDatabase())
    request = RecoveryProposalCreate.model_validate(proposal_payload()).model_dump(mode="json")
    created = repository.create_proposal(
        request, "11111111-1111-4111-8111-111111111111", "a" * 64
    )
    approved = repository.decide_proposal(
        request["proposal_id"], "W-CONTROL-01", "approved", "path clear"
    )
    command = approved["command"]
    repository.mark_command_sent(command["command_id"])
    repository.record_command_ack("PK_01", {
        "command_id": command["command_id"],
        "proposal_sha256": created["proposal_sha256"],
        "accepted": True,
        "reason_code": "ACTION_ACCEPTED",
    })
    result = {
        "command_id": command["command_id"],
        "proposal_sha256": created["proposal_sha256"],
        "success": True, "status": "succeeded", "terminal": True,
        "clearance_after_m": 0.5, "elapsed_seconds": 1.0,
        "safety_intervened": False,
    }
    repository.record_execution_result("PK_01", result)
    repository.record_execution_result("PK_01", result)

    assert repository.get_execution_result(command["command_id"]) == result
    open_items = repository.list_open_recoveries("PK_01")
    assert open_items[0]["proposal"]["proposal_id"] == request["proposal_id"]
    assert open_items[0]["execution"]["result"] == result
    assert recovery_mysql_db.one(
        "SELECT delivery_status FROM recovery_command_outbox WHERE command_id=%s",
        (command["command_id"],),
    )["delivery_status"] == "acknowledged"

    completion = build_completion(
        request,
        result,
        (0.2, 0.0, 0.0, 1.0, 0.0, 0.3, 0.5, 0.8, 0.2),
    )
    digest = hashlib.sha256(
        json.dumps(completion, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    repository.complete_recovery_step(
        request["recovery_episode_uuid"], request["step_no"], completion,
        command["command_id"], digest,
    )
    assert repository.list_open_recoveries("PK_01") == []
    assert len(repository.list_training_rows()) == 1
