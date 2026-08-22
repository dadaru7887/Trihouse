"""Public product-only order API boundary tests."""

from copy import deepcopy

from fastapi.testclient import TestClient

from fms_gateway.app.main import create_app
from fms_gateway.app.repositories import (
    IdempotencyConflict,
    OutboundOrderInsufficientStock,
)


REQUEST = {
    "external_reference": "DEMO-ORDER-ALL-ZONES-001",
    "priority": "normal",
    "allow_partial_fulfillment": False,
    "items": [{"product_code": "SKU-MANDARIN", "quantity": 1}],
}


class RecordingRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, str]] = []
        self.failure: Exception | None = None

    def create_outbound_order(self, request: dict, idempotency_key: str) -> dict:
        self.calls.append((deepcopy(request), idempotency_key))
        if self.failure is not None:
            raise self.failure
        return {
            "job_id": 7,
            "job_code": "OUT-7",
            "external_reference": request.get("external_reference"),
            "state": "queued",
            "requested_quantity": 1,
            "fulfillable_quantity": 1,
            "outstanding_quantity": 0,
            "items": [
                {
                    "line_no": 1,
                    "product_code": "SKU-MANDARIN",
                    "requested_quantity": 1,
                    "reserved_quantity": 1,
                    "outstanding_quantity": 0,
                }
            ],
        }


def test_public_order_route_requires_an_idempotency_key() -> None:
    response = TestClient(create_app(RecordingRepository())).post(
        "/api/v1/orders", json=REQUEST
    )

    assert response.status_code == 422


def test_public_order_route_accepts_an_order_without_a_worker_identity() -> None:
    """EN: Anonymous order intake must not invent an employee identity.

    KO: 익명 주문 접수는 존재하지 않는 직원 식별자를 만들어서는 안 된다.
    """
    repository = RecordingRepository()
    response = TestClient(create_app(repository)).post(
        "/api/v1/orders",
        headers={"Idempotency-Key": "anonymous-order-001"},
        json=REQUEST,
    )

    assert response.status_code == 201, response.text
    assert repository.calls[0][0]["requested_by"] is None


def test_public_order_route_accepts_only_product_order_fields() -> None:
    repository = RecordingRepository()
    body = {**REQUEST, "destination_id": "PACKING-01", "robot_id": "PK_01"}

    response = TestClient(create_app(repository)).post(
        "/api/v1/orders",
        headers={"Idempotency-Key": "order-api-001"},
        json=body,
    )

    assert response.status_code == 422
    assert repository.calls == []


def test_public_order_route_passes_the_anonymous_order_to_one_repository_command() -> None:
    repository = RecordingRepository()

    response = TestClient(create_app(repository)).post(
        "/api/v1/orders",
        headers={"Idempotency-Key": "order-api-001"},
        json=REQUEST,
    )

    assert response.status_code == 201
    assert response.json()["outstanding_quantity"] == 0
    assert repository.calls == [({**REQUEST, "requested_by": None}, "order-api-001")]


def test_full_only_shortage_is_a_stable_atomic_conflict() -> None:
    repository = RecordingRepository()
    repository.failure = OutboundOrderInsufficientStock(
        ({"line_no": 1, "product_code": "SKU-ORANGE", "outstanding_quantity": 1},)
    )

    response = TestClient(create_app(repository)).post(
        "/api/v1/orders",
        headers={"Idempotency-Key": "order-api-shortage"},
        json=REQUEST,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INSUFFICIENT_STOCK"
    assert response.json()["detail"]["shortages"][0]["outstanding_quantity"] == 1


def test_reusing_an_order_key_for_another_payload_is_a_conflict() -> None:
    repository = RecordingRepository()
    repository.failure = IdempotencyConflict()

    response = TestClient(create_app(repository)).post(
        "/api/v1/orders",
        headers={"Idempotency-Key": "order-api-reused"},
        json=REQUEST,
    )

    assert response.status_code == 409
