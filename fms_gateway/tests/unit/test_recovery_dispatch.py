import asyncio
import pytest

from fms_gateway.app.recovery_dispatch import dispatch_pending_once
from fms_gateway.app.recovery_repository import (
    InMemoryRecoveryRepository,
    RecoveryProposalConflict,
)


class Repository:
    def __init__(self):
        self.sent = []

    def list_pending_commands(self):
        return [{"command_id": "cmd-1", "device_id": "PK_01", "payload": {"type": "recovery_command"}}]

    def mark_command_sent(self, command_id):
        self.sent.append(command_id)


class Links:
    def __init__(self, delivered):
        self.delivered = delivered
        self.calls = []

    async def push(self, device_id, payload):
        self.calls.append((device_id, payload))
        return self.delivered


def test_dispatch_marks_sent_only_after_socket_write_succeeds() -> None:
    repository = Repository()
    links = Links(True)

    count = asyncio.run(dispatch_pending_once(repository, links))

    assert count == 1
    assert links.calls == [("PK_01", {"type": "recovery_command"})]
    assert repository.sent == ["cmd-1"]


def test_disconnected_robot_leaves_command_pending_for_retry() -> None:
    repository = Repository()
    links = Links(False)

    assert asyncio.run(dispatch_pending_once(repository, links)) == 0
    assert repository.sent == []


def test_ack_identity_and_execution_result_are_persisted_separately() -> None:
    repository = InMemoryRecoveryRepository()
    command = {
        "command_id": "11111111-1111-4111-8111-111111111111",
        "device_id": "PK_01",
        "proposal_sha256": "a" * 64,
        "delivery_status": "sent",
        "payload": {"type": "recovery_command"},
    }
    repository.command_outbox.append(command)

    repository.record_command_ack("PK_01", {
        "command_id": command["command_id"], "proposal_sha256": "a" * 64,
        "accepted": True, "reason_code": "ACTION_ACCEPTED",
    })
    repository.record_execution_result("PK_01", {
        "command_id": command["command_id"], "proposal_sha256": "a" * 64,
        "success": True, "status": "succeeded", "terminal": True,
    })

    assert repository.command_outbox[0]["delivery_status"] == "acknowledged"
    assert repository.get_execution_result(command["command_id"])["status"] == "succeeded"

    with pytest.raises(RecoveryProposalConflict):
        repository.record_execution_result("PK_02", {
            "command_id": command["command_id"], "proposal_sha256": "a" * 64,
            "success": True, "status": "succeeded", "terminal": True,
        })
