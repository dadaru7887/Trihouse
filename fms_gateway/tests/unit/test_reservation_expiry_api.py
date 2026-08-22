"""만료 회수와 이상 승인의 HTTP 경계.

원장 의미는 MySQL integration test 가 증명한다. 여기서는 관제 UI 가 실제로 붙을 수
있는 모양인지 — 열린 목록을 읽고 승인을 보낼 수 있는지 — 만 본다. 승인 경로가 없으면
이상은 열리기만 하고 아무도 닫지 못한다(설계 10절).
"""

from fastapi.testclient import TestClient

from fms_gateway.app.main import create_app
from fms_gateway.app.repositories import InMemoryFmsRepository


ASSIGNMENT = {
    "revision": 1,
    "mobile_id": "PK_01",
    "omx_id": "OMX_01",
    "packing_dock_code": "PACKING-01-DOCK-01",
    "charger_code": "TRIHOUSE-TEST-01-CHG-01",
}


def _job() -> dict[str, object]:
    return {
        "job_code": "OUT-EXPIRE-001",
        "operation_type": "outbound",
        "priority": "normal",
        "external_reference": "order-expire",
        "context": {},
        "steps": [
            {
                "step_no": 1,
                "action_type": "navigate",
                "executor_type": "mobile",
                "target_location_id": 12,
                "input": {"waypoint": "PACK-01"},
            },
        ],
    }


def _client_with_overdue_job() -> tuple[TestClient, InMemoryFmsRepository, int]:
    repository = InMemoryFmsRepository(
        seed_workers=[
            {"worker_id": "W-FIELD-01", "role": "operator", "active": True}
        ]
    )
    client = TestClient(create_app(repository))
    created = client.post("/internal/v1/jobs", json=_job())
    job_id = int(created.json()["job_id"])
    assigned = client.post(f"/internal/v1/jobs/{job_id}/assignment", json=ASSIGNMENT)
    assert assigned.status_code == 200, assigned.text
    repository.force_reservation_expiry(job_id)
    return client, repository, job_id


def test_the_sweep_reports_what_it_released():
    client, _repository, job_id = _client_with_overdue_job()

    response = client.post("/internal/v1/reservations/expire")

    assert response.status_code == 200, response.text
    expired = response.json()["expired"]
    assert {entry["job_id"] for entry in expired} == {job_id}
    assert all(entry["job_active"] for entry in expired)


def test_mixed_zone_expiry_reports_the_later_omx_as_a_device():
    """EN: Expiry must classify OMX_02 as a device, not a location.

    KO: 만료 처리에서 OMX_02를 위치가 아닌 장비로 분류해야 한다.
    """
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository))
    job = _job()
    job["steps"] = [
        {
            "step_no": 10,
            "action_type": "prepare",
            "executor_type": "arm",
            "input": {"dependencies": [], "omx_id": "OMX_01"},
        },
        {
            "step_no": 20,
            "action_type": "prepare",
            "executor_type": "arm",
            "input": {"dependencies": [10], "omx_id": "OMX_02"},
        },
    ]
    job_id = client.post("/internal/v1/jobs", json=job).json()["job_id"]
    assigned = client.post(
        f"/internal/v1/jobs/{job_id}/assignment",
        json={**ASSIGNMENT, "omx_ids": ["OMX_01", "OMX_02"]},
    )
    assert assigned.status_code == 200, assigned.text
    repository.force_reservation_expiry(job_id)

    expired = client.post("/internal/v1/reservations/expire").json()["expired"]

    omx_02 = next(entry for entry in expired if entry["device_id"] == "OMX_02")
    assert omx_02["location_id"] is None


def test_a_job_with_nothing_overdue_is_left_alone():
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository))
    created = client.post("/internal/v1/jobs", json=_job())
    job_id = int(created.json()["job_id"])
    client.post(f"/internal/v1/jobs/{job_id}/assignment", json=ASSIGNMENT)

    response = client.post("/internal/v1/reservations/expire")

    assert response.status_code == 200
    assert response.json()["expired"] == []


def test_the_open_anomalies_are_readable_and_closable_by_a_person():
    client, _repository, job_id = _client_with_overdue_job()
    client.post("/internal/v1/reservations/expire")

    listed = client.get("/api/v1/operations/anomalies", params={"state": "open"})
    assert listed.status_code == 200, listed.text
    anomalies = listed.json()
    assert anomalies
    assert anomalies[0]["job_id"] == job_id

    correlation_uuid = anomalies[0]["correlation_uuid"]
    acknowledged = client.post(
        f"/api/v1/operations/anomalies/{correlation_uuid}/acknowledge",
        json={"worker_id": "W-FIELD-01", "note": "robot was parked"},
    )

    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["acknowledged_by"] == "W-FIELD-01"
    remaining = client.get(
        "/api/v1/operations/anomalies", params={"state": "open"}
    ).json()
    assert correlation_uuid not in {entry["correlation_uuid"] for entry in remaining}


def test_acknowledging_an_unknown_anomaly_is_not_found():
    client = TestClient(create_app(InMemoryFmsRepository()))

    response = client.post(
        "/api/v1/operations/anomalies/00000000-0000-0000-0000-000000000000/acknowledge",
        json={"worker_id": "W-FIELD-01", "note": "nothing here"},
    )

    assert response.status_code == 404


def test_an_unregistered_actor_cannot_close_an_anomaly():
    client, _repository, _job_id = _client_with_overdue_job()
    client.post("/internal/v1/reservations/expire")
    correlation_uuid = client.get(
        "/api/v1/operations/anomalies", params={"state": "open"}
    ).json()[0]["correlation_uuid"]

    response = client.post(
        f"/api/v1/operations/anomalies/{correlation_uuid}/acknowledge",
        json={"worker_id": "NOT-A-WORKER", "note": "who am I"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ACTIVE_WORKER_REQUIRED"
