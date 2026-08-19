"""비상 판단이 실제 MySQL 원장에 어떻게 적히는지 확인한다.

in-memory 저장소는 상태 전이만 흉내 낸다. 여기서 확인하는 것은 실제 스키마가
받아 주는지다 — `incidents.state` 의 CHECK, `operation_events.safety_decision` 의
허용값, 그리고 incident FK 까지 함께 걸린다.
"""

import os

from fms_gateway.app.config import Settings
from fms_gateway.app.database import Database
from fms_gateway.app.repositories import (
    EmergencyDecisionConflict,
    IdempotencyConflict,
    IncidentNotFound,
    MySqlFmsRepository,
)

import pytest


def repository() -> MySqlFmsRepository:
    return MySqlFmsRepository(
        Database(
            Settings(
                host=os.environ.get("FMS_DB_HOST", "127.0.0.1"),
                port=int(os.environ.get("FMS_DB_PORT", "3307")),
                user=os.environ.get("FMS_DB_USER", "fms_gateway"),
                password=os.environ.get("FMS_DB_PASSWORD", "test_gateway_password"),
                database="trihouse_fms",
                pool_size=2,
            )
        )
    )


def _open_incident(mysql_db, code: str = "INC-FALL-0001") -> int:
    mysql_db.execute(
        """
        INSERT INTO incidents
          (incident_code, incident_type, severity, state, description)
        VALUES (%s, 'worker_emergency', 'critical', 'active', 'worker collapsed')
        """,
        (code,),
    )
    mysql_db.connection.commit()
    return int(
        mysql_db.one(
            "SELECT incident_id FROM incidents WHERE incident_code = %s", (code,)
        )["incident_id"]
    )


def _worker(mysql_db, worker_id: str = "W-SAFE-01") -> None:
    mysql_db.execute(
        """
        INSERT INTO workers (worker_id, worker_code, name, role, active)
        VALUES (%s, %s, %s, 'safety_manager', 1)
        """,
        (worker_id, worker_id.replace("W-", ""), worker_id),
    )
    mysql_db.connection.commit()


def test_raising_the_alarm_moves_the_incident_and_writes_one_safety_event(mysql_db):
    _worker(mysql_db)
    incident_id = _open_incident(mysql_db)

    result = repository().decide_incident_emergency(
        incident_id,
        {"worker_id": "W-SAFE-01", "decision": "RAISE_ALARM", "reason": "WORKER_FALL"},
        "emergency-1-raiseAlarm",
    )

    assert result["state"] == "acknowledged"
    incident = mysql_db.one(
        """
        SELECT state, acknowledged_by_worker_id, acknowledged_at,
               resolved_by_worker_id, resolved_at
        FROM incidents WHERE incident_id = %s
        """,
        (incident_id,),
    )
    assert incident["state"] == "acknowledged"
    assert incident["acknowledged_by_worker_id"] == "W-SAFE-01"
    assert incident["acknowledged_at"] is not None
    # 경보를 올린 것은 사건을 닫은 것이 아니다.
    assert incident["resolved_by_worker_id"] is None
    assert incident["resolved_at"] is None

    events = mysql_db.all(
        """
        SELECT category, event_type, severity, safety_decision, actor_worker_id
        FROM operation_events WHERE incident_id = %s
        """,
        (incident_id,),
    )
    assert len(events) == 1
    assert events[0]["category"] == "safety"
    assert events[0]["event_type"] == "incident.decision.recorded"
    assert events[0]["safety_decision"] == "stopped"
    assert events[0]["actor_worker_id"] == "W-SAFE-01"


def test_continuing_work_closes_the_incident_and_records_approval(mysql_db):
    _worker(mysql_db)
    incident_id = _open_incident(mysql_db, "INC-FALL-0002")

    result = repository().decide_incident_emergency(
        incident_id,
        {"worker_id": "W-SAFE-01", "decision": "CONTINUE_WORK", "reason": "cleared"},
        "emergency-2-continueWork",
    )

    assert result["state"] == "resolved"
    incident = mysql_db.one(
        "SELECT state, resolved_by_worker_id, resolved_at FROM incidents "
        "WHERE incident_id = %s",
        (incident_id,),
    )
    assert incident["state"] == "resolved"
    assert incident["resolved_by_worker_id"] == "W-SAFE-01"
    assert incident["resolved_at"] is not None
    event = mysql_db.one(
        "SELECT safety_decision FROM operation_events WHERE incident_id = %s",
        (incident_id,),
    )
    assert event["safety_decision"] == "approved"


def test_a_retry_with_the_same_key_does_not_write_a_second_decision(mysql_db):
    _worker(mysql_db)
    incident_id = _open_incident(mysql_db, "INC-FALL-0003")
    gateway = repository()
    request = {
        "worker_id": "W-SAFE-01",
        "decision": "RAISE_ALARM",
        "reason": "WORKER_FALL",
    }

    first = gateway.decide_incident_emergency(incident_id, request, "emergency-3-raise")
    replay = gateway.decide_incident_emergency(incident_id, request, "emergency-3-raise")

    assert replay == first
    events = mysql_db.all(
        "SELECT event_id FROM operation_events WHERE incident_id = %s", (incident_id,)
    )
    assert len(events) == 1, "재시도가 두 번째 판단으로 남으면 감사 기록이 거짓이 된다"


def test_the_same_key_cannot_carry_a_different_decision(mysql_db):
    _worker(mysql_db)
    incident_id = _open_incident(mysql_db, "INC-FALL-0004")
    gateway = repository()
    gateway.decide_incident_emergency(
        incident_id,
        {"worker_id": "W-SAFE-01", "decision": "RAISE_ALARM", "reason": "fall"},
        "emergency-4-raise",
    )

    with pytest.raises(IdempotencyConflict):
        gateway.decide_incident_emergency(
            incident_id,
            {"worker_id": "W-SAFE-01", "decision": "CONTINUE_WORK", "reason": "fall"},
            "emergency-4-raise",
        )


def test_a_closed_incident_refuses_a_late_decision(mysql_db):
    _worker(mysql_db)
    incident_id = _open_incident(mysql_db, "INC-FALL-0005")
    gateway = repository()
    gateway.decide_incident_emergency(
        incident_id,
        {"worker_id": "W-SAFE-01", "decision": "CONTINUE_WORK", "reason": "cleared"},
        "emergency-5-close",
    )

    with pytest.raises(EmergencyDecisionConflict) as failure:
        gateway.decide_incident_emergency(
            incident_id,
            {"worker_id": "W-SAFE-01", "decision": "RAISE_ALARM", "reason": "late"},
            "emergency-5-late",
        )
    assert failure.value.code == "INCIDENT_NOT_DECIDABLE"


def test_an_unregistered_worker_cannot_decide(mysql_db):
    _open_incident(mysql_db, "INC-FALL-0006")
    incident_id = int(
        mysql_db.one(
            "SELECT incident_id FROM incidents WHERE incident_code = 'INC-FALL-0006'"
        )["incident_id"]
    )

    with pytest.raises(EmergencyDecisionConflict) as failure:
        repository().decide_incident_emergency(
            incident_id,
            {"worker_id": "W-GHOST-99", "decision": "RAISE_ALARM", "reason": "fall"},
            "emergency-6-raise",
        )
    assert failure.value.code == "ACTIVE_WORKER_REQUIRED"
    incident = mysql_db.one(
        "SELECT state FROM incidents WHERE incident_id = %s", (incident_id,)
    )
    assert incident["state"] == "active", "거절된 판단이 원장을 움직이면 안 된다"


def test_an_unknown_incident_is_reported_rather_than_created(mysql_db):
    _worker(mysql_db)

    with pytest.raises(IncidentNotFound):
        repository().decide_incident_emergency(
            999_999,
            {"worker_id": "W-SAFE-01", "decision": "RAISE_ALARM", "reason": "fall"},
            "emergency-missing-raise",
        )
