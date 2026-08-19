"""운영자의 비상 판단이 운영 원장에 실제로 적히는지 확인한다.

이 경로가 없던 동안 관제 화면의 비상 버튼은 존재하지 않는 라우트를 불러 404 로
조용히 사라졌다. 안전 판단은 눌렸다는 사실 자체가 감사 대상이므로, 여기서 막히면
원장에는 아무 일도 없었던 것이 된다.
"""

from fastapi.testclient import TestClient

from fms_gateway.app.main import create_app
from fms_gateway.app.repositories import InMemoryFmsRepository


def _client_with_incident(incident_id: int = 1, state: str = "active"):
    repository = InMemoryFmsRepository()
    repository.open_incident(incident_id, incident_code="INC-FALL-0001", state=state)
    return TestClient(create_app(repository)), repository


def _decide(client, incident_id, decision, *, key, worker="W-OP-01", reason="fall"):
    return client.post(
        f"/api/v1/incidents/{incident_id}/decision",
        json={"worker_id": worker, "decision": decision, "reason": reason},
        headers={"Idempotency-Key": key},
    )


def test_raising_the_alarm_acknowledges_the_incident_and_names_the_operator():
    client, repository = _client_with_incident()

    response = _decide(client, 1, "RAISE_ALARM", key="emergency-1-raiseAlarm")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "acknowledged"
    assert body["decision"] == "RAISE_ALARM"
    assert body["decided_by"] == "W-OP-01"
    assert body["incident_code"] == "INC-FALL-0001"
    # 원장이 실제로 옮겨졌는지 본다. 응답만 맞고 상태가 안 바뀌면 의미가 없다.
    assert repository._incidents[1]["state"] == "acknowledged"


def test_continuing_work_closes_the_incident():
    client, repository = _client_with_incident()

    response = _decide(client, 1, "CONTINUE_WORK", key="emergency-1-continueWork")

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "resolved"
    assert repository._incidents[1]["state"] == "resolved"


def test_the_same_key_replays_instead_of_deciding_twice():
    client, _ = _client_with_incident()
    key = "emergency-1-raiseAlarm"

    first = _decide(client, 1, "RAISE_ALARM", key=key)
    second = _decide(client, 1, "RAISE_ALARM", key=key)

    assert first.status_code == 200, first.text
    # 재시도가 두 번째 판단으로 기록되면 안 된다. 같은 결과를 그대로 돌려준다.
    assert second.status_code == 200, second.text
    assert second.json() == first.json()


def test_reusing_a_key_for_a_different_decision_is_refused():
    client, _ = _client_with_incident()
    key = "emergency-1-raiseAlarm"

    _decide(client, 1, "RAISE_ALARM", key=key)
    conflict = _decide(client, 1, "CONTINUE_WORK", key=key)

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_a_closed_incident_cannot_be_reopened_by_a_late_decision():
    client, _ = _client_with_incident(state="resolved")

    response = _decide(client, 1, "RAISE_ALARM", key="emergency-1-raiseAlarm")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INCIDENT_NOT_DECIDABLE"


def test_an_acknowledged_incident_can_still_be_closed_but_not_realarmed():
    client, _ = _client_with_incident(state="acknowledged")

    realarm = _decide(client, 1, "RAISE_ALARM", key="emergency-1-raiseAlarm")
    assert realarm.status_code == 409
    assert realarm.json()["detail"]["code"] == "INCIDENT_NOT_DECIDABLE"

    closed = _decide(client, 1, "CONTINUE_WORK", key="emergency-1-continueWork")
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "resolved"


def test_an_unknown_incident_is_not_silently_accepted():
    client, _ = _client_with_incident()

    response = _decide(client, 404, "RAISE_ALARM", key="emergency-404-raiseAlarm")

    assert response.status_code == 404


def test_an_inactive_worker_cannot_decide():
    client, repository = _client_with_incident()

    response = _decide(
        client, 1, "RAISE_ALARM", key="emergency-1-raiseAlarm", worker="W-GONE-99"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ACTIVE_WORKER_REQUIRED"
    assert repository._incidents[1]["state"] == "active"


def test_the_idempotency_key_header_is_required():
    client, _ = _client_with_incident()

    response = client.post(
        "/api/v1/incidents/1/decision",
        json={"worker_id": "W-OP-01", "decision": "RAISE_ALARM", "reason": "fall"},
    )

    assert response.status_code == 422


def test_an_unknown_decision_is_rejected_before_it_reaches_the_ledger():
    client, repository = _client_with_incident()

    response = client.post(
        "/api/v1/incidents/1/decision",
        json={"worker_id": "W-OP-01", "decision": "SHUT_DOWN", "reason": "fall"},
        headers={"Idempotency-Key": "emergency-1-shutdown"},
    )

    assert response.status_code == 422
    assert repository._incidents[1]["state"] == "active"
