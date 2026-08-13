"""Wire-contract tests for Control Tower's FMS Gateway HTTP boundary."""

from __future__ import annotations

import json
from typing import Any

from control_tower.gateway.fms_client import (
    FMSGatewayHttpClient,
    JobCreateRequest,
    JobCreateResponse,
    JobStepCreateRequest,
    RmfDispatchAcceptanceRequest,
    RmfDispatchAcceptanceResponse,
    RmfDispatchClaimRequest,
    RmfDispatchClaimResponse,
    StepDispatchRequest,
    StepDispatchResponse,
)


class _Response:
    def __init__(self, payload: dict[str, Any], status: int) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class RecordingOpener:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.requests: list[tuple[Any, float]] = []

    def open(self, request: Any, timeout: float) -> _Response:
        self.requests.append((request, timeout))
        return self.response


def test_create_job_posts_typed_payload_to_configured_gateway() -> None:
    """A wrong endpoint or lossy DTO serialization must fail at this boundary."""
    opener = RecordingOpener(
        _Response(
            {
                "job_id": 42,
                "job_code": "OUT-42",
                "state": "queued",
                "steps": [
                    {
                        "job_step_id": 420,
                        "step_no": 10,
                        "action_type": "navigate",
                        "executor_type": "mobile",
                        "target_location_id": 101,
                        "state": "pending",
                    }
                ],
            },
            201,
        )
    )
    client = FMSGatewayHttpClient(
        "http://127.0.0.1:18080/root/",
        opener=opener,
        timeout=3.5,
    )
    request = JobCreateRequest(
        job_code="OUT-42",
        operation_type="outbound",
        priority="high",
        requested_by="control-tower",
        source_location_id=100,
        destination_location_id=200,
        context={"order_id": "ORDER-42"},
        steps=(
            JobStepCreateRequest(
                step_no=10,
                action_type="navigate",
                executor_type="mobile",
                target_location_id=101,
                input={"source": "current", "target": "inbound_waiting"},
            ),
        ),
    )

    response = client.create_job(request)

    sent, timeout = opener.requests[0]
    assert sent.full_url == "http://127.0.0.1:18080/root/internal/v1/jobs"
    assert sent.method == "POST"
    assert sent.get_header("Content-type") == "application/json"
    assert timeout == 3.5
    assert json.loads(sent.data) == {
        "job_code": "OUT-42",
        "operation_type": "outbound",
        "priority": "high",
        "requested_by": "control-tower",
        "source_location_id": 100,
        "destination_location_id": 200,
        "context": {"order_id": "ORDER-42"},
        "steps": [
            {
                "step_no": 10,
                "action_type": "navigate",
                "executor_type": "mobile",
                "target_location_id": 101,
                "input": {"source": "current", "target": "inbound_waiting"},
            }
        ],
    }
    assert response == JobCreateResponse.from_dict(
        {
            "job_id": 42,
            "job_code": "OUT-42",
            "state": "queued",
            "steps": [
                {
                    "job_step_id": 420,
                    "step_no": 10,
                    "action_type": "navigate",
                    "executor_type": "mobile",
                    "target_location_id": 101,
                    "state": "pending",
                }
            ],
        }
    )


def test_dispatch_step_sends_idempotency_header_and_returns_typed_response() -> None:
    """Dispatches without their stable idempotency key can duplicate physical work."""
    payload = {
        "message_id": "9db03d28-d35e-49bb-948a-e42f4daaf2ce",
        "idempotency_key": "dispatch-job-42-step-420",
        "job_id": 42,
        "job_step_id": 420,
        "channel": "rmf",
        "message_type": "rmf_dispatch",
        "state": "pending",
        "payload": {"target_location_id": 101},
    }
    opener = RecordingOpener(_Response(payload, 200))
    client = FMSGatewayHttpClient("http://gateway:8080", opener=opener)

    response = client.dispatch_step(
        420,
        StepDispatchRequest(
            idempotency_key="dispatch-job-42-step-420",
            actor="control-tower",
            occurred_at="2026-08-12T12:30:00+09:00",
            assigned_device_id="PK_01",
            retry=True,
        ),
    )

    sent, _ = opener.requests[0]
    assert sent.full_url == "http://gateway:8080/internal/v1/job-steps/420/dispatch"
    assert sent.get_header("Idempotency-key") == "dispatch-job-42-step-420"
    assert json.loads(sent.data) == {
        "actor": "control-tower",
        "occurred_at": "2026-08-12T12:30:00+09:00",
        "assigned_device_id": "PK_01",
        "retry": True,
    }
    assert response == StepDispatchResponse.from_dict(payload)


def test_claim_rmf_dispatches_posts_worker_identity_and_returns_typed_records() -> None:
    """The worker must claim work through FMS instead of reading an outbox database."""
    dispatch = {
        "message_id": "message-1",
        "idempotency_key": "dispatch-step-10",
        "job_id": 7,
        "job_step_id": 100,
        "channel": "rmf",
        "message_type": "dispatch_task_request",
        "state": "sent",
        "payload": {"input": {"waypoint": "INBOUND_WAITING"}},
    }
    opener = RecordingOpener(_Response({"dispatches": [dispatch]}, 200))
    client = FMSGatewayHttpClient("http://gateway:8080/", opener=opener)

    response = client.claim_rmf_dispatches(RmfDispatchClaimRequest("worker-1", 4))

    sent, _ = opener.requests[0]
    assert sent.full_url == "http://gateway:8080/internal/v1/rmf/dispatches/claim"
    assert json.loads(sent.data) == {"worker_id": "worker-1", "limit": 4}
    assert response == RmfDispatchClaimResponse(
        dispatches=(StepDispatchResponse.from_dict(dispatch),)
    )


def test_report_rmf_acceptance_posts_exact_optional_assignment_fields() -> None:
    """The RMF booking result must return through FMS, never a local repository."""
    opener = RecordingOpener(
        _Response(
            {
                "message_id": "message-1",
                "job_step_id": 100,
                "state": "acknowledged",
                "rmf_task_id": "rmf-task-1",
            },
            200,
        )
    )
    client = FMSGatewayHttpClient("http://gateway:8080", opener=opener)

    response = client.report_rmf_acceptance(
        "message-1",
        RmfDispatchAcceptanceRequest(
            accepted=True,
            rmf_task_id="rmf-task-1",
            assigned_device_id="PK_01",
            detail="queued",
        ),
    )

    sent, _ = opener.requests[0]
    assert sent.full_url == (
        "http://gateway:8080/internal/v1/rmf/dispatches/message-1/acceptance"
    )
    assert json.loads(sent.data) == {
        "accepted": True,
        "rmf_task_id": "rmf-task-1",
        "assigned_device_id": "PK_01",
        "detail": "queued",
    }
    assert response == RmfDispatchAcceptanceResponse(
        message_id="message-1",
        job_step_id=100,
        state="acknowledged",
        rmf_task_id="rmf-task-1",
    )
