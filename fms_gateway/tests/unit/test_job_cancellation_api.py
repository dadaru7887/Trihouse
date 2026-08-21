"""취소 엔드포인트의 HTTP 경계 — 상태코드와 필수 헤더.

원장 의미(예약 해제, 멱등 재생, 끝난 job 거부)는 MySQL integration test 가 증명한다.
여기서는 그 결과가 안정적인 HTTP 계약으로 나오는지만 본다.
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

CANCEL = {"reason": "stuck outside RMF", "requested_by": "W-OP-01"}


def _job() -> dict[str, object]:
    return {
        "job_code": "OUT-CANCEL-001",
        "operation_type": "outbound",
        "priority": "normal",
        "external_reference": "order-cancel",
        "context": {},
        "steps": [
            {
                "step_no": 1,
                "action_type": "navigate",
                "executor_type": "mobile",
                "target_location_id": 12,
                "input": {"waypoint": "PACK-01"},
            },
            {
                "step_no": 2,
                "action_type": "load",
                "executor_type": "arm",
                "target_location_id": 12,
                "input": {"sku": "SKU-1"},
            },
        ],
    }


def _client_with_assigned_job() -> tuple[TestClient, int]:
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository))
    created = client.post("/internal/v1/jobs", json=_job())
    assert created.status_code == 201, created.text
    job_id = int(created.json()["job_id"])
    assigned = client.post(
        f"/internal/v1/jobs/{job_id}/assignment", json=ASSIGNMENT
    )
    assert assigned.status_code == 200, assigned.text
    return client, job_id


def test_cancelling_returns_the_resources_it_handed_back():
    client, job_id = _client_with_assigned_job()

    response = client.post(
        f"/internal/v1/jobs/{job_id}/cancel",
        headers={"Idempotency-Key": "cancel-api-1"},
        json=CANCEL,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job_id"] == job_id
    assert body["state"] == "cancelled"
    assert body["released_device_ids"] == ["OMX_01", "PK_01"]
    assert client.get(f"/api/v1/jobs/{job_id}").json()["state"] == "cancelled"


def test_cancelling_a_mixed_zone_job_releases_both_arms_and_one_pinky():
    """EN: Cancelling a shared Job must release every later-zone OMX.

    KO: 공통 Job을 취소하면 뒤 구역의 OMX도 모두 해제해야 한다.
    """
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository))
    job = _job()
    job["steps"] = [
        {
            "step_no": 10,
            "action_type": "prepare",
            "executor_type": "arm",
            "target_location_id": 11,
            "input": {"dependencies": [], "omx_id": "OMX_01"},
        },
        {
            "step_no": 20,
            "action_type": "prepare",
            "executor_type": "arm",
            "target_location_id": 12,
            "input": {"dependencies": [10], "omx_id": "OMX_02"},
        },
    ]
    job_id = client.post("/internal/v1/jobs", json=job).json()["job_id"]
    assigned = client.post(
        f"/internal/v1/jobs/{job_id}/assignment",
        json={**ASSIGNMENT, "omx_ids": ["OMX_01", "OMX_02"]},
    )
    assert assigned.status_code == 200, assigned.text

    response = client.post(
        f"/internal/v1/jobs/{job_id}/cancel",
        headers={"Idempotency-Key": "cancel-api-mixed"},
        json=CANCEL,
    )

    assert response.status_code == 200, response.text
    assert response.json()["released_device_ids"] == ["OMX_01", "OMX_02", "PK_01"]


def test_the_idempotency_key_is_required():
    client, job_id = _client_with_assigned_job()

    response = client.post(f"/internal/v1/jobs/{job_id}/cancel", json=CANCEL)

    assert response.status_code == 422


def test_replaying_the_key_repeats_the_same_body():
    client, job_id = _client_with_assigned_job()
    headers = {"Idempotency-Key": "cancel-api-replay"}

    first = client.post(
        f"/internal/v1/jobs/{job_id}/cancel", headers=headers, json=CANCEL
    )
    second = client.post(
        f"/internal/v1/jobs/{job_id}/cancel", headers=headers, json=CANCEL
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_the_same_key_with_a_different_reason_is_a_conflict():
    client, job_id = _client_with_assigned_job()
    headers = {"Idempotency-Key": "cancel-api-fingerprint"}
    client.post(f"/internal/v1/jobs/{job_id}/cancel", headers=headers, json=CANCEL)

    response = client.post(
        f"/internal/v1/jobs/{job_id}/cancel",
        headers=headers,
        json={"reason": "another reason", "requested_by": "W-OP-01"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_an_unknown_job_is_not_found():
    client = TestClient(create_app(InMemoryFmsRepository()))

    response = client.post(
        "/internal/v1/jobs/4242/cancel",
        headers={"Idempotency-Key": "cancel-api-missing"},
        json=CANCEL,
    )

    assert response.status_code == 404


def test_a_finished_job_cannot_be_cancelled():
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository))
    created = client.post("/internal/v1/jobs", json=_job())
    job_id = int(created.json()["job_id"])
    repository.force_job_state(job_id, "completed")

    response = client.post(
        f"/internal/v1/jobs/{job_id}/cancel",
        headers={"Idempotency-Key": "cancel-api-finished"},
        json=CANCEL,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "JOB_ALREADY_FINISHED"
