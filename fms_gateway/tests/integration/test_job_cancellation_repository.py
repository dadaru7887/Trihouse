"""RMF 밖에서 멈춘 job 을 한 트랜잭션으로 취소하는 Gateway 경로.

예약 lifecycle 자체는 `rmf_task_repository` 가 이미 처리하지만 그 경로는 RMF task
update 가 도착해야 돈다. RMF 에 제출되기 전에 멈춘 job 은 그 경로를 타지 못하고
예약을 영원히 쥔다. 취소를 스크립트가 아니라 Gateway 에 두는 이유는 행 잠금과 상태
전이 불변식이 이미 이 저장소 안에 있기 때문이다 — 두 곳에서 같은 전이를 하면
어긋난다.
"""

from contextlib import contextmanager
from copy import deepcopy

import pytest

from conftest import mysql_connection
from fms_gateway.app.repositories import (
    IdempotencyConflict,
    JobCancellationConflict,
    JobNotFound,
    MySqlFmsRepository,
)
from test_outbound_order_repository import DEMO_ORDERS, install_active_map, rows, scalar
from test_read_api import real_client


pytestmark = pytest.mark.integration


ASSIGNMENT = {
    "revision": 1,
    "mobile_id": "PK_01",
    "omx_id": "OMX_01",
    "packing_dock_code": "PACKING-01-DOCK-01",
    "charger_code": "TRIHOUSE-TEST-01-CHG-01",
}


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


def _assigned_job(
    key: str, *, install_map: bool = True, product_code: str | None = None
) -> int:
    """RMF 에 닿기 전 자원을 쥔 job — 지금 실가동에서 멈춰 있는 것과 같은 모양이다."""
    if install_map:
        install_active_map()
    request = deepcopy(DEMO_ORDERS[5]["request"])
    request["external_reference"] = f"CANCEL-{key}"
    if product_code is not None:
        # 재고는 유한하다 — SKU 마다 stored lot 이 하나씩이라 한 테스트에서 주문을
        # 두 번 넣으려면 다른 상품이어야 한다.
        request["items"] = [{"product_code": product_code, "quantity": 1}]
    response = real_client().post(
        "/api/v1/orders",
        headers={"Idempotency-Key": f"cancel-order-{key}"},
        json=request,
    )
    assert response.status_code == 201, response.text
    job_id = int(response.json()["job_id"])
    _repository().assign_job_resources(job_id, ASSIGNMENT)
    return job_id


def _execute(sql: str, params: tuple[object, ...] = ()) -> None:
    connection = mysql_connection(database="trihouse_fms")
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params)
        connection.commit()
    finally:
        cursor.close()
        connection.close()


def test_cancelling_releases_every_resource_the_job_was_holding(seeded_schema) -> None:
    job_id = _assigned_job("release")

    result = _repository().cancel_job(
        job_id,
        {"reason": "P0 hardware test cleanup", "requested_by": "W-OP-01"},
        "cancel-release-1",
    )

    assert result["job_id"] == job_id
    assert result["state"] == "cancelled"
    assert result["released_device_ids"] == ["OMX_01", "PK_01"]
    assert len(result["cancelled_reservation_ids"]) == 3

    assert rows("SELECT state FROM jobs WHERE job_id=%s", (job_id,))[0]["state"] == (
        "cancelled"
    )
    assert scalar(
        "SELECT COUNT(*) FROM reservations WHERE job_id=%s AND state IN "
        "('reserved','in_use')",
        (job_id,),
    ) == 0
    assert scalar(
        "SELECT COUNT(*) FROM reservations WHERE job_id=%s AND state='cancelled'",
        (job_id,),
    ) == 3
    assert scalar(
        "SELECT COUNT(*) FROM job_steps WHERE job_id=%s AND state='pending'",
        (job_id,),
    ) == 0
    assert scalar(
        "SELECT COUNT(*) FROM operation_events "
        "WHERE job_id=%s AND event_type='job.cancelled'",
        (job_id,),
    ) == 1


def test_a_finished_step_keeps_its_outcome_when_the_job_is_cancelled(
    seeded_schema,
) -> None:
    """취소는 아직 끝나지 않은 것만 닫는다. 이미 일어난 일을 되쓰면 원장이 거짓이 된다."""
    job_id = _assigned_job("succeeded-step")
    _execute(
        "UPDATE job_steps SET state='succeeded' WHERE job_id=%s AND action_type='pick'",
        (job_id,),
    )
    finished = {
        int(row["job_step_id"])
        for row in rows(
            "SELECT job_step_id FROM job_steps WHERE job_id=%s AND state='succeeded'",
            (job_id,),
        )
    }
    assert finished

    result = _repository().cancel_job(
        job_id, {"reason": "stuck outside RMF", "requested_by": "W-OP-01"}, "cancel-succ-1"
    )

    assert finished.isdisjoint(result["cancelled_step_ids"])
    still_succeeded = {
        int(row["job_step_id"])
        for row in rows(
            "SELECT job_step_id FROM job_steps WHERE job_id=%s AND state='succeeded'",
            (job_id,),
        )
    }
    assert still_succeeded == finished
    assert scalar(
        "SELECT COUNT(*) FROM job_steps WHERE job_id=%s AND state='cancelled'",
        (job_id,),
    ) == len(result["cancelled_step_ids"])


def test_replaying_the_same_idempotency_key_repeats_the_first_answer(
    seeded_schema,
) -> None:
    job_id = _assigned_job("idempotent")
    gateway = _repository()

    first = gateway.cancel_job(
        job_id, {"reason": "stuck outside RMF", "requested_by": "W-OP-01"}, "cancel-same"
    )
    second = gateway.cancel_job(
        job_id, {"reason": "stuck outside RMF", "requested_by": "W-OP-01"}, "cancel-same"
    )

    assert first == second
    assert scalar(
        "SELECT COUNT(*) FROM operation_events "
        "WHERE job_id=%s AND event_type='job.cancelled'",
        (job_id,),
    ) == 1


def test_the_same_key_with_a_different_reason_is_a_conflict(seeded_schema) -> None:
    job_id = _assigned_job("fingerprint")
    gateway = _repository()
    gateway.cancel_job(
        job_id, {"reason": "first reason", "requested_by": "W-OP-01"}, "cancel-fp"
    )

    with pytest.raises(IdempotencyConflict):
        gateway.cancel_job(
            job_id, {"reason": "second reason", "requested_by": "W-OP-01"}, "cancel-fp"
        )


def test_cancelling_an_already_cancelled_job_is_not_an_error(seeded_schema) -> None:
    """두 번째 취소는 새 키로 와도 같은 사실을 돌려준다 — 되돌릴 것이 없을 뿐이다."""
    job_id = _assigned_job("twice")
    gateway = _repository()
    gateway.cancel_job(
        job_id, {"reason": "stuck outside RMF", "requested_by": "W-OP-01"}, "cancel-twice-1"
    )

    again = gateway.cancel_job(
        job_id, {"reason": "stuck outside RMF", "requested_by": "W-OP-01"}, "cancel-twice-2"
    )

    assert again["state"] == "cancelled"
    assert again["cancelled_reservation_ids"] == []
    assert again["cancelled_step_ids"] == []


@pytest.mark.parametrize("terminal_state", ["completed", "failed"])
def test_a_finished_job_cannot_be_cancelled(seeded_schema, terminal_state) -> None:
    """끝난 일을 취소했다고 말하면 원장이 거짓이 된다."""
    job_id = _assigned_job(f"terminal-{terminal_state}")
    _execute("UPDATE jobs SET state=%s WHERE job_id=%s", (terminal_state, job_id))

    with pytest.raises(JobCancellationConflict):
        _repository().cancel_job(
            job_id, {"reason": "too late", "requested_by": "W-OP-01"}, f"cancel-{terminal_state}"
        )

    assert rows("SELECT state FROM jobs WHERE job_id=%s", (job_id,))[0]["state"] == (
        terminal_state
    )


def test_cancelling_an_unknown_job_is_not_found(seeded_schema) -> None:
    with pytest.raises(JobNotFound):
        _repository().cancel_job(
            999_999, {"reason": "nothing here", "requested_by": "W-OP-01"}, "cancel-missing"
        )


def test_cancelling_closes_the_outbox_so_no_worker_picks_the_job_up_again(
    seeded_schema,
) -> None:
    """살아 있는 outbox 메시지를 남기면 RMF worker 가 그것을 집는다.

    2026-08-18 실측: 취소된 step 을 가리키는 `sent` 메시지 두 건이 남아 RMF worker 가
    그것을 집고 acceptance 를 보고하다 Gateway 에서 409 를 받고 죽었다. dispatch 주기가
    통째로 멈춰 다른 job 도 로봇까지 가지 못했다.
    """
    job_id = _assigned_job("outbox")
    # 지금 실행 가능한 것은 첫 step 뿐이다 — Gateway 가 그 순서를 지킨다.
    step_id = int(
        rows(
            "SELECT job_step_id FROM job_steps WHERE job_id=%s ORDER BY step_no LIMIT 1",
            (job_id,),
        )[0]["job_step_id"]
    )
    _repository().dispatch_step(
        step_id,
        {"actor": "control-tower", "assigned_device_id": "OMX_01"},
        f"cancel-outbox-{job_id}",
    )
    assert scalar(
        "SELECT COUNT(*) FROM integration_messages "
        "WHERE job_step_id=%s AND state IN ('pending','sent')",
        (step_id,),
    ) == 1

    result = _repository().cancel_job(
        job_id, {"reason": "stuck outside RMF", "requested_by": "W-OP-01"}, "cancel-outbox"
    )

    assert scalar(
        "SELECT COUNT(*) FROM integration_messages "
        "WHERE job_step_id=%s AND state IN ('pending','sent')",
        (step_id,),
    ) == 0
    closed = rows(
        "SELECT state, last_error FROM integration_messages WHERE job_step_id=%s",
        (step_id,),
    )[0]
    assert closed["state"] == "failed"
    assert "cancel" in str(closed["last_error"]).lower()
    assert result["cancelled_message_ids"] != []
    # 이미 끝난 메시지는 되쓰지 않는다.
    assert scalar(
        "SELECT COUNT(*) FROM integration_messages WHERE state='acknowledged'"
    ) == scalar(
        "SELECT COUNT(*) FROM integration_messages WHERE state='acknowledged'"
    )


def test_a_delivered_outbox_message_keeps_its_outcome_when_the_job_is_cancelled(
    seeded_schema,
) -> None:
    job_id = _assigned_job("outbox-done")
    step_id = int(
        rows(
            "SELECT job_step_id FROM job_steps WHERE job_id=%s AND executor_type='arm' "
            "ORDER BY step_no LIMIT 1",
            (job_id,),
        )[0]["job_step_id"]
    )
    _repository().dispatch_step(
        step_id,
        {"actor": "control-tower", "assigned_device_id": "OMX_01"},
        f"cancel-outbox-done-{job_id}",
    )
    _execute(
        "UPDATE integration_messages SET state='acknowledged' WHERE job_step_id=%s",
        (step_id,),
    )

    _repository().cancel_job(
        job_id, {"reason": "stuck outside RMF", "requested_by": "W-OP-01"}, "cancel-outbox-done"
    )

    assert rows(
        "SELECT state FROM integration_messages WHERE job_step_id=%s", (step_id,)
    )[0]["state"] == "acknowledged"


def test_cancelling_frees_the_resource_for_the_next_job(seeded_schema) -> None:
    """회수의 목적은 원장 정리가 아니라 다음 주문이 실제로 그 로봇을 잡는 것이다."""
    first = _assigned_job("handover-1")
    _repository().cancel_job(
        first, {"reason": "stuck outside RMF", "requested_by": "W-OP-01"}, "cancel-handover"
    )

    second = _assigned_job(
        "handover-2", install_map=False, product_code="SKU-STRAWBERRY"
    )

    assert scalar(
        "SELECT COUNT(*) FROM reservations "
        "WHERE job_id=%s AND device_id='PK_01' AND state='reserved'",
        (second,),
    ) == 1
