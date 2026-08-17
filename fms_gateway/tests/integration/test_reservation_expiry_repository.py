"""만료된 예약을 회수하고, 위험한 만료만 사람에게 올리는 Gateway 경로.

만료 자체는 정상일 수 있다 — job 이 이미 끝났는데 예약만 남은 경우다. 위험한 것은
자원은 풀렸는데 **로봇이 아직 거기 있을 수 있는** 상태이고, P0 에서 정직하게 잡을 수
있는 신호는 하나뿐이다: 예약이 만료 해제됐는데 그 job 의 step 이 아직 끝나지 않았다.

이상 보고를 `incidents` 가 아니라 `operation_events` 에 올리는 이유는 스키마가 그것을
허용하지 않기 때문이다. `chk_incidents_type` 에 `reservation_expired_while_active` 가
없고 `chk_incidents_state` 에 `open` 이 없으며 `incidents` 에는 `job_id` 컬럼이 아예
없다. `operation_events` 에는 셋 다 있고 `event_uuid` 가 UNIQUE 라 중복 open 을 DB 가
막는다.
"""

from contextlib import contextmanager
from copy import deepcopy

import pytest

from conftest import mysql_connection
from fms_gateway.app.repositories import (
    AnomalyAcknowledgementConflict,
    AnomalyNotFound,
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


def _execute(sql: str, params: tuple[object, ...] = ()) -> None:
    connection = mysql_connection(database="trihouse_fms")
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params)
        connection.commit()
    finally:
        cursor.close()
        connection.close()


def _assigned_job(
    key: str, *, install_map: bool = True, product_code: str | None = None
) -> int:
    if install_map:
        install_active_map()
    request = deepcopy(DEMO_ORDERS[5]["request"])
    request["external_reference"] = f"EXPIRE-{key}"
    if product_code is not None:
        request["items"] = [{"product_code": product_code, "quantity": 1}]
    response = real_client().post(
        "/api/v1/orders",
        headers={"Idempotency-Key": f"expire-order-{key}"},
        json=request,
    )
    assert response.status_code == 201, response.text
    job_id = int(response.json()["job_id"])
    _repository().assign_job_resources(job_id, ASSIGNMENT)
    return job_id


def _age_reservations(job_id: int) -> None:
    """`chk_reservations_expiry` 가 expires_at > created_at 을 요구하므로 둘 다 민다."""
    _execute(
        """
        UPDATE reservations
        SET created_at = NOW(6) - INTERVAL 12 HOUR,
            expires_at = NOW(6) - INTERVAL 8 HOUR
        WHERE job_id = %s
        """,
        (job_id,),
    )


def test_overdue_reservations_are_released_and_each_one_is_recorded(
    seeded_schema,
) -> None:
    job_id = _assigned_job("overdue")
    _age_reservations(job_id)

    result = _repository().expire_reservations()

    assert len(result["expired"]) == 3
    assert {entry["job_id"] for entry in result["expired"]} == {job_id}
    assert scalar(
        "SELECT COUNT(*) FROM reservations WHERE job_id=%s AND state='expired'",
        (job_id,),
    ) == 3
    assert scalar(
        "SELECT COUNT(*) FROM operation_events "
        "WHERE job_id=%s AND event_type='reservation.expired'",
        (job_id,),
    ) == 3
    assert rows(
        "SELECT released_at FROM reservations WHERE job_id=%s ORDER BY reservation_id",
        (job_id,),
    )[0]["released_at"] is not None


def test_a_reservation_that_has_not_expired_is_left_alone(seeded_schema) -> None:
    job_id = _assigned_job("fresh")

    result = _repository().expire_reservations()

    assert result["expired"] == []
    assert scalar(
        "SELECT COUNT(*) FROM reservations WHERE job_id=%s AND state='reserved'",
        (job_id,),
    ) == 3


def test_running_the_sweep_twice_does_not_record_the_same_expiry_again(
    seeded_schema,
) -> None:
    job_id = _assigned_job("twice")
    _age_reservations(job_id)
    gateway = _repository()

    gateway.expire_reservations()
    second = gateway.expire_reservations()

    assert second["expired"] == []
    assert scalar(
        "SELECT COUNT(*) FROM operation_events "
        "WHERE job_id=%s AND event_type='reservation.expired'",
        (job_id,),
    ) == 3


def test_expiring_while_the_job_still_has_work_left_opens_an_anomaly(
    seeded_schema,
) -> None:
    """자원은 풀렸는데 로봇이 아직 거기 있을 수 있다 — 사람이 봐야 하는 유일한 신호."""
    job_id = _assigned_job("anomaly")
    _age_reservations(job_id)

    result = _repository().expire_reservations()

    assert all(entry["job_active"] for entry in result["expired"])
    open_anomalies = _repository().list_open_anomalies()
    assert [anomaly["job_id"] for anomaly in open_anomalies] == [job_id] * 3
    assert scalar(
        "SELECT COUNT(*) FROM operation_events "
        "WHERE job_id=%s AND event_type='reservation.expired_while_active' "
        "AND severity='warning'",
        (job_id,),
    ) == 3


def test_expiring_after_the_job_finished_is_not_an_anomaly(seeded_schema) -> None:
    job_id = _assigned_job("finished")
    _age_reservations(job_id)
    _execute("UPDATE job_steps SET state='succeeded' WHERE job_id=%s", (job_id,))
    _execute("UPDATE jobs SET state='completed' WHERE job_id=%s", (job_id,))

    result = _repository().expire_reservations()

    assert result["expired"]
    assert not any(entry["job_active"] for entry in result["expired"])
    assert _repository().list_open_anomalies() == []


def test_a_second_sweep_cannot_open_a_second_anomaly_for_the_same_reservation(
    seeded_schema,
) -> None:
    """경보 폭주는 운영에서 제일 위험하다. 결정적 event_uuid 로 DB 가 막는다."""
    job_id = _assigned_job("storm")
    _age_reservations(job_id)
    gateway = _repository()
    gateway.expire_reservations()

    _execute(
        "UPDATE reservations SET state='reserved', released_at=NULL WHERE job_id=%s",
        (job_id,),
    )
    gateway.expire_reservations()

    assert scalar(
        "SELECT COUNT(*) FROM operation_events "
        "WHERE job_id=%s AND event_type='reservation.expired_while_active'",
        (job_id,),
    ) == 3


def test_acknowledging_closes_the_anomaly_and_names_who_closed_it(
    seeded_schema,
) -> None:
    job_id = _assigned_job("acknowledge")
    _age_reservations(job_id)
    gateway = _repository()
    gateway.expire_reservations()
    anomaly = gateway.list_open_anomalies()[0]

    closed = gateway.acknowledge_anomaly(
        anomaly["correlation_uuid"],
        {"worker_id": "W-OP-01", "note": "robot was parked, resource is free"},
    )

    assert closed["correlation_uuid"] == anomaly["correlation_uuid"]
    assert closed["acknowledged_by"] == "W-OP-01"
    remaining = [entry["correlation_uuid"] for entry in gateway.list_open_anomalies()]
    assert anomaly["correlation_uuid"] not in remaining
    assert len(remaining) == 2


def test_acknowledging_twice_is_not_an_error_and_records_one_closure(
    seeded_schema,
) -> None:
    job_id = _assigned_job("ack-twice")
    _age_reservations(job_id)
    gateway = _repository()
    gateway.expire_reservations()
    anomaly = gateway.list_open_anomalies()[0]
    payload = {"worker_id": "W-OP-01", "note": "checked"}

    first = gateway.acknowledge_anomaly(anomaly["correlation_uuid"], payload)
    second = gateway.acknowledge_anomaly(anomaly["correlation_uuid"], payload)

    assert first == second
    assert scalar(
        "SELECT COUNT(*) FROM operation_events "
        "WHERE job_id=%s AND event_type='reservation.anomaly.acknowledged'",
        (job_id,),
    ) == 1


def test_only_a_registered_worker_can_acknowledge(seeded_schema) -> None:
    """승인은 사람의 판단이다 — 등록되지 않은 행위자가 닫으면 감사 추적이 끊긴다."""
    _assigned_job("unknown-worker")
    _age_reservations(scalar("SELECT MAX(job_id) FROM jobs"))
    gateway = _repository()
    gateway.expire_reservations()
    anomaly = gateway.list_open_anomalies()[0]

    with pytest.raises(AnomalyAcknowledgementConflict) as error:
        gateway.acknowledge_anomaly(
            anomaly["correlation_uuid"],
            {"worker_id": "NOT-A-WORKER", "note": "who am I"},
        )

    assert error.value.code == "ACTIVE_WORKER_REQUIRED"
    assert len(gateway.list_open_anomalies()) == 3


def test_acknowledging_something_that_was_never_opened_is_not_found(
    seeded_schema,
) -> None:
    with pytest.raises(AnomalyNotFound):
        _repository().acknowledge_anomaly(
            "00000000-0000-0000-0000-000000000000",
            {"worker_id": "W-OP-01", "note": "nothing here"},
        )


def test_cancelling_the_job_first_means_the_expiry_is_no_longer_an_anomaly(
    seeded_schema,
) -> None:
    """취소가 자원을 이미 돌려줬으면 만료가 볼 것이 없다 — 8절 1번과 2번의 경계."""
    job_id = _assigned_job("cancel-first")
    _repository().cancel_job(
        job_id, {"reason": "stuck outside RMF", "requested_by": "W-OP-01"}, "expire-cancel"
    )
    _age_reservations(job_id)

    result = _repository().expire_reservations()

    assert result["expired"] == []
    assert _repository().list_open_anomalies() == []
