"""`pinky` 채널에 성격이 다른 두 가지가 흐른다 — executor 는 자기 것만 집어야 한다.

같은 계약을 `tests/unit/test_job_runtime_api.py` 가 InMemory 로 이미 고정해 두었다.
그런데 운영은 MySQL 로 돈다. 2026-08-19 실가동에서 InMemory 는 초록인 채로 MySQL
경로만 이 결함을 그대로 안고 있었고, job 18 step 20 은 주행이 성공했는데도
executor 가 남의 행을 집어 409 를 맞는 바람에 `failed` 로 닫혔다. 그래서 이 계약은
두 저장소 양쪽에 각각 있어야 한다.
"""

from contextlib import contextmanager
from copy import deepcopy

import pytest

from conftest import mysql_connection
from fms_gateway.app.repositories import MySqlFmsRepository
from test_outbound_order_repository import DEMO_ORDERS, install_active_map, rows
from test_read_api import real_client


pytestmark = pytest.mark.integration


ASSIGNMENT = {
    "revision": 1,
    "mobile_id": "PK_01",
    "omx_id": "OMX_01",
    "packing_dock_code": "PACKING-01-DOCK-01",
    "charger_code": "TRIHOUSE-TEST-01-CHG-01",
}

RMF_TASK_ID = "compose.dispatch-executor-channel"


class _ConnectionDatabase:
    @contextmanager
    def connection(self):
        connection = mysql_connection(database="trihouse_fms")
        try:
            yield connection
        finally:
            connection.close()


def _repository() -> MySqlFmsRepository:
    return MySqlFmsRepository(_ConnectionDatabase())


def _navigate_step_awaiting_its_robot() -> int:
    """RMF 가 낙찰했고 로봇이 명령을 claim 한 직후의 mobile/navigate step."""
    install_active_map()
    request = deepcopy(DEMO_ORDERS[5]["request"])
    request["external_reference"] = "EXECUTOR-CHANNEL"
    client = real_client()
    created = client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": "executor-channel-order"},
        json=request,
    )
    assert created.status_code == 201, created.text
    job_id = int(created.json()["job_id"])
    _repository().assign_job_resources(job_id, ASSIGNMENT)

    steps = rows(
        "SELECT job_step_id, step_no, executor_type, action_type FROM job_steps"
        " WHERE job_id = %s ORDER BY step_no",
        (job_id,),
    )
    # 계획의 첫 걸음은 로봇팔 pick 이다. 그것이 끝나야 주행이 현재 step 이 된다.
    pick = steps[0]
    assert (pick["executor_type"], pick["action_type"]) == ("arm", "pick"), steps
    client.post(
        f"/internal/v1/job-steps/{pick['job_step_id']}/dispatch",
        headers={"Idempotency-Key": "executor-channel-pick-dispatch"},
        json={"actor": "control-tower", "assigned_device_id": "OMX_01"},
    )
    finished = client.post(
        f"/internal/v1/job-steps/{pick['job_step_id']}/outcome",
        headers={"Idempotency-Key": "executor-channel-pick-outcome"},
        json={
            "outcome": "succeeded",
            "assignment_revision": ASSIGNMENT["revision"],
            "method_code": "OMX_SIMULATED_CONTRACT",
            "actor_device_id": "OMX_01",
        },
    )
    assert finished.status_code == 200, finished.text

    step_id = next(
        step["job_step_id"]
        for step in steps
        if (step["executor_type"], step["action_type"]) == ("mobile", "navigate")
    )

    dispatched = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": "executor-channel-dispatch"},
        json={"actor": "control-tower", "assigned_device_id": "PK_01"},
    )
    assert dispatched.status_code in (200, 201), dispatched.text
    message_id = dispatched.json()["message_id"]

    client.post("/internal/v1/rmf/dispatches/claim", json={"worker_id": "rmf-worker"})
    accepted = client.post(
        f"/internal/v1/rmf/dispatches/{message_id}/acceptance",
        json={
            "accepted": True,
            "rmf_task_id": RMF_TASK_ID,
            "assigned_device_id": "PK_01",
        },
    )
    assert accepted.status_code == 200, accepted.text

    # 로봇이 명령을 claim 하면 같은 `pinky` 채널에 `execution_command` 가 남는다.
    claimed = client.post(
        f"/internal/v1/rmf/tasks/{RMF_TASK_ID}/commands/claim",
        json={
            "robot_id": "PK_01",
            "execution_id": "exec-1",
            "map_revision": "trihouse_test_01:rev",
        },
    )
    assert claimed.status_code == 200, claimed.text
    return step_id


def test_executor_claim_ignores_robot_command_records_on_the_same_channel(
    seeded_schema,
) -> None:
    step_id = _navigate_step_awaiting_its_robot()

    claimed = _repository().claim_executor_dispatches(
        "executor", ("omx", "pinky"), 10
    )

    assert "execution_command" not in {row["message_type"] for row in claimed}, claimed
    assert [row for row in claimed if row["job_step_id"] == step_id] == [], claimed
