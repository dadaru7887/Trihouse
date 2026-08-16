"""Worker completion HTTP contract tests."""

from copy import deepcopy
from datetime import datetime

from fastapi.testclient import TestClient

from fms_gateway.app.main import create_app
from fms_gateway.app.repositories import (
    IdempotencyConflict,
    JobNotFound,
    ManualAcknowledgementRequired,
    WorkerCompletionConflict,
)


REQUEST = {
    "worker_id": "W-OP-01",
    "completion_note": "packed and checked",
    "acknowledged_manual_item_ids": [12],
}


def _job() -> dict:
    return {
        "job_id": 7,
        "job_code": "OUT-7",
        "operation_type": "outbound",
        "priority": "normal",
        "state": "running",
        "requested_by": "W-OP-01",
        "external_reference": "ORDER-7",
        "source_location_id": None,
        "destination_location_id": 8,
        "due_at": None,
        "context": {
            "assignment": {
                "revision": 1,
                "mobile_id": "PK_01",
                "omx_id": "OMX_01",
                "packing_dock_code": "PACKING-01-DOCK-01",
                "charger_code": "TRIHOUSE-TEST-01-CHG-01",
            }
        },
        "created_at": datetime(2026, 8, 16, 9, 0),
        "items": [
            {
                "job_item_id": 12,
                "product_code": "SKU-MANDARIN",
                "requested_qty": 1,
                "completed_qty": 1,
                "lot_id": 3,
                "verification_state": "manual_review",
                "metadata": {"fulfillment_state": "MANUAL_FULFILLMENT_REQUIRED"},
            }
        ],
        "steps": [],
    }


class RecordingRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict, str]] = []
        self.failure: Exception | None = None

    def complete_worker_packing(
        self, job_id: int, request: dict, idempotency_key: str
    ) -> dict:
        self.calls.append((job_id, deepcopy(request), idempotency_key))
        if self.failure is not None:
            raise self.failure
        return _job()


def test_worker_completion_requires_idempotency_key() -> None:
    response = TestClient(create_app(RecordingRepository())).post(
        "/api/v1/jobs/7/worker-completion", json=REQUEST
    )

    assert response.status_code == 422


def test_worker_completion_forwards_acknowledgements_to_one_gateway_transaction() -> None:
    repository = RecordingRepository()

    response = TestClient(create_app(repository)).post(
        "/api/v1/jobs/7/worker-completion",
        headers={"Idempotency-Key": "complete-7"},
        json=REQUEST,
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["job_item_id"] == 12
    assert repository.calls == [(7, REQUEST, "complete-7")]


def test_worker_completion_rejects_unknown_fields_and_duplicate_acknowledgements() -> None:
    repository = RecordingRepository()
    invalid = {**REQUEST, "acknowledged_manual_item_ids": [12, 12], "robot_id": "PK_02"}

    response = TestClient(create_app(repository)).post(
        "/api/v1/jobs/7/worker-completion",
        headers={"Idempotency-Key": "complete-invalid"},
        json=invalid,
    )

    assert response.status_code == 422
    assert repository.calls == []


def test_worker_completion_maps_domain_failures_to_stable_http_statuses() -> None:
    cases = (
        (JobNotFound(), 404, "job not found"),
        (ManualAcknowledgementRequired((12,)), 409, "MANUAL_ACKNOWLEDGEMENT_REQUIRED"),
        (WorkerCompletionConflict("PACKING_NOT_READY"), 409, "PACKING_NOT_READY"),
        (IdempotencyConflict(), 409, "IDEMPOTENCY_CONFLICT"),
    )
    for failure, status, code in cases:
        repository = RecordingRepository()
        repository.failure = failure

        response = TestClient(create_app(repository)).post(
            "/api/v1/jobs/7/worker-completion",
            headers={"Idempotency-Key": f"complete-{code}"},
            json=REQUEST,
        )

        assert response.status_code == status
        assert code in str(response.json()["detail"])
