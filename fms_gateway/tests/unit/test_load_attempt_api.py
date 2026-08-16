"""Gateway load-attempt and operator recovery HTTP contracts."""

from copy import deepcopy

from fastapi.testclient import TestClient

from fms_gateway.app.main import create_app


LOAD = {
    "attempt_id": "00000000-0000-0000-0000-000000000101",
    "job_id": 7,
    "item_id": 12,
    "handover_group_id": "group-ambient",
    "assignment_revision": 4,
    "pinky_id": "PK_01",
    "omx_id": "OMX_01",
    "result": "LOAD_CONFIRMED",
    "criteria": {"expected_item": True},
    "observations": {"qr": "SKU-MANDARIN", "aruco": 17},
    "metrics": {"confidence": 0.99},
    "evidence_refs": ["fixture://load/101"],
    "policy_name": "load-contract",
    "policy_version": "1",
    "model_name": "fixture-observer",
    "model_version": "1",
}


class RecordingRepository:
    def __init__(self) -> None:
        self.calls = []

    def record_load_attempt(self, step_id, request, key):
        self.calls.append(("load", step_id, deepcopy(request), key))
        return {**request, "departure_allowed": request["result"] == "LOAD_CONFIRMED"}

    def record_pick_recovery(self, step_id, request, key):
        self.calls.append(("recovery", step_id, deepcopy(request), key))
        return {**request, "retry_no": 1, "drop_hold": False}


def test_load_attempt_requires_complete_lineage_and_forbids_intake_flag() -> None:
    repository = RecordingRepository()
    client = TestClient(create_app(repository))

    accepted = client.post(
        "/internal/v1/job-steps/31/load-attempts",
        headers={"Idempotency-Key": "load-101"},
        json=LOAD,
    )
    forbidden = client.post(
        "/internal/v1/job-steps/31/load-attempts",
        headers={"Idempotency-Key": "load-102"},
        json={**LOAD, "allow_partial_fulfillment": True},
    )

    assert accepted.status_code == 200
    assert forbidden.status_code == 422
    assert repository.calls == [("load", 31, LOAD, "load-101")]


def test_recovery_exposes_only_two_choices_while_drop_clearance_is_a_fact() -> None:
    repository = RecordingRepository()
    client = TestClient(create_app(repository))
    base = {"job_id": 7, "item_id": 12, "operator_id": "W-OP-01"}

    retry = client.post(
        "/internal/v1/job-steps/31/pick-recovery",
        headers={"Idempotency-Key": "retry-1"},
        json={**base, "choice": "재시도"},
    )
    invalid = client.post(
        "/internal/v1/job-steps/31/pick-recovery",
        headers={"Idempotency-Key": "retry-invalid"},
        json={**base, "choice": "부분 출고"},
    )
    recovered = client.post(
        "/internal/v1/job-steps/31/recovery-facts",
        headers={"Idempotency-Key": "object-recovered"},
        json={**base, "fact": "object-recovered"},
    )

    assert retry.status_code == 200
    assert invalid.status_code == 422
    assert recovered.status_code == 200
    assert repository.calls[0][2]["choice"] == "재시도"
    assert repository.calls[1][2]["fact"] == "object-recovered"
