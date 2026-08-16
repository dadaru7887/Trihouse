"""Tests for the FMS-backed RMF dispatch worker."""

from __future__ import annotations

from control_tower.gateway.fms_client import (
    RmfDispatchAcceptanceRequest,
    RmfDispatchAcceptanceResponse,
    RmfDispatchClaimResponse,
    StepDispatchResponse,
)
from control_tower.rmf_adapter.order_task import RmfAssignmentWindow
from control_tower.rmf_adapter.rmf_gateway_worker import RmfGatewayWorker
from control_tower.rmf_adapter.task_api import DispatchAcceptance


class FakeGateway:
    def __init__(self, dispatches: tuple[StepDispatchResponse, ...]) -> None:
        self.dispatches = dispatches
        self.claims = []
        self.acceptances: list[tuple[str, RmfDispatchAcceptanceRequest]] = []

    def claim_rmf_dispatches(self, request):
        self.claims.append(request)
        claimed, self.dispatches = self.dispatches, ()
        return RmfDispatchClaimResponse(claimed)

    def report_rmf_acceptance(self, message_id, request):
        self.acceptances.append((message_id, request))
        return RmfDispatchAcceptanceResponse(
            message_id=message_id,
            job_step_id=100,
            state="acknowledged" if request.accepted else "failed",
            rmf_task_id=request.rmf_task_id,
        )


class FakeTransport:
    def __init__(self, acceptance: DispatchAcceptance) -> None:
        self.acceptance = acceptance
        self.submissions = []

    def submit(self, request_id, payload, timeout_s):
        self.submissions.append((request_id, payload, timeout_s))
        return self.acceptance


class RaisingTransport:
    def submit(self, request_id, payload, timeout_s):
        raise TimeoutError("response lost after publish")


def dispatch_record(**payload_overrides) -> StepDispatchResponse:
    payload = {
        "request": {"assigned_device_id": "PK_01"},
        "job_id": 7,
        "job_step_id": 100,
        "step_no": 10,
        "action_type": "navigate",
        "target_location_id": 11,
        "target_waypoint": "INBOUND_WAITING",
        "fleet_name": None,
        "request_time_ms": 1_786_500_000_000,
        "input": {},
    }
    payload.update(payload_overrides)
    return StepDispatchResponse(
        message_id="message-1",
        idempotency_key="dispatch-1",
        job_id=7,
        job_step_id=100,
        channel="rmf",
        message_type="dispatch_task_request",
        state="sent",
        payload=payload,
    )


def test_worker_claims_builds_rmf_request_and_reports_assignment() -> None:
    """A claimed record must become one correlated RMF request and FMS acceptance."""
    gateway = FakeGateway((dispatch_record(),))
    transport = FakeTransport(
        DispatchAcceptance(
            accepted=True,
            rmf_task_id="rmf-task-1",
            rmf_status="queued",
            assignment=RmfAssignmentWindow(
                task_id="rmf-task-1",
                fleet_name="project1_pinky",
                robot_name="PK_01",
                start_ms=1,
                end_ms=2,
            ),
        )
    )
    worker = RmfGatewayWorker(
        gateway,
        transport,
        worker_id="rmf-worker-1",
        default_fleet_name="project1_pinky",
        timeout_s=2.5,
    )

    report = worker.run_once(limit=4)

    assert gateway.claims[0].worker_id == "rmf-worker-1"
    assert gateway.claims[0].limit == 4
    request_id, payload, timeout = transport.submissions[0]
    assert request_id == "message-1"
    assert timeout == 2.5
    assert payload == {
        "type": "dispatch_task_request",
        "request": {
            "category": "compose",
            "description": {
                "category": "go_to_place",
                "phases": [
                    {
                        "activity": {
                            "category": "go_to_place",
                            "description": {
                                "one_of": [{"waypoint": "INBOUND_WAITING"}]
                            },
                        }
                    }
                ],
            },
            "unix_millis_request_time": 1_786_500_000_000,
            "unix_millis_earliest_start_time": 1_786_500_000_000,
            "requester": "trihouse_control_tower",
            "fleet_name": "project1_pinky",
            "robot_name": "PK_01",
            "labels": ["job_step:100", "request:message-1", "robot:PK_01"],
        },
    }
    assert gateway.acceptances == [
        (
            "message-1",
            RmfDispatchAcceptanceRequest(
                accepted=True,
                rmf_task_id="rmf-task-1",
                assigned_device_id="PK_01",
                detail="queued",
            ),
        )
    ]
    assert report.claimed == report.accepted == 1
    assert report.rejected == 0


def test_worker_reports_rmf_rejection_without_inventing_task_mapping() -> None:
    """An RMF rejection must be durably reported as rejection, not retried locally."""
    gateway = FakeGateway((dispatch_record(fleet_name="special_fleet"),))
    transport = FakeTransport(
        DispatchAcceptance(
            accepted=False,
            reason_code="RMF_TASK_REJECTED",
            detail="unknown waypoint",
        )
    )
    worker = RmfGatewayWorker(
        gateway,
        transport,
        worker_id="worker",
        default_fleet_name="project1_pinky",
    )

    report = worker.run_once()

    assert transport.submissions[0][1]["request"]["fleet_name"] == "special_fleet"
    assert gateway.acceptances == [
        (
            "message-1",
            RmfDispatchAcceptanceRequest(
                accepted=False,
                detail="RMF_TASK_REJECTED: unknown waypoint",
            ),
        )
    ]
    assert report.rejected == 1


def test_worker_keeps_post_publish_timeout_indeterminate() -> None:
    gateway = FakeGateway((dispatch_record(),))
    worker = RmfGatewayWorker(
        gateway,
        RaisingTransport(),
        worker_id="worker",
        default_fleet_name="project1_pinky",
    )

    report = worker.run_once()

    assert gateway.acceptances == []
    assert report.indeterminate == 1
    assert report.rejected == 0


def test_worker_fails_closed_when_booking_has_no_authoritative_assignment() -> None:
    """Requested robot affinity is not evidence that RMF assigned that robot."""
    gateway = FakeGateway((dispatch_record(),))
    transport = FakeTransport(
        DispatchAcceptance(
            accepted=True,
            rmf_task_id="rmf-task-pending-assignment",
            rmf_status="queued",
            assignment=None,
        )
    )
    worker = RmfGatewayWorker(
        gateway,
        transport,
        worker_id="worker",
        default_fleet_name="project1_pinky",
    )

    report = worker.run_once()

    assert gateway.acceptances == [
        (
            "message-1",
            RmfDispatchAcceptanceRequest(
                accepted=False,
                rmf_task_id="rmf-task-pending-assignment",
                detail="RMF_ASSIGNMENT_PENDING",
            ),
        )
    ]
    assert report.accepted == 0
    assert report.rejected == 0
    assert report.indeterminate == 1


def test_worker_rejects_malformed_claim_without_submitting_to_ros() -> None:
    """Missing executable waypoint data must fail closed at the FMS boundary."""
    gateway = FakeGateway((dispatch_record(target_waypoint=None),))
    transport = FakeTransport(DispatchAcceptance(True, rmf_task_id="unused"))
    worker = RmfGatewayWorker(
        gateway,
        transport,
        worker_id="worker",
        default_fleet_name="project1_pinky",
    )

    report = worker.run_once()

    assert transport.submissions == []
    assert gateway.acceptances[0][0] == "message-1"
    assert gateway.acceptances[0][1].accepted is False
    assert gateway.acceptances[0][1].detail == "INVALID_RMF_DISPATCH: target_waypoint is required"
    assert report.rejected == 1


def test_worker_rejects_claim_without_assigned_device_before_ros_submit() -> None:
    """Claimed work without its fenced device identity must not become physical work."""
    gateway = FakeGateway((dispatch_record(request={"assigned_device_id": None}),))
    transport = FakeTransport(DispatchAcceptance(True, rmf_task_id="unused"))
    worker = RmfGatewayWorker(
        gateway,
        transport,
        worker_id="worker",
        default_fleet_name="project1_pinky",
    )

    report = worker.run_once()

    assert transport.submissions == []
    assert gateway.acceptances[0][1] == RmfDispatchAcceptanceRequest(
        accepted=False,
        detail="INVALID_RMF_DISPATCH: assigned_device_id is required",
    )
    assert report.rejected == 1


def test_rmf_substituting_another_pinky_never_overwrites_the_assignment() -> None:
    """RMF가 다른 로봇을 낙찰해도 Control Tower 배정을 덮어쓰지 않는다."""
    gateway = FakeGateway((dispatch_record(),))
    transport = FakeTransport(
        DispatchAcceptance(
            True,
            rmf_task_id="rmf-task-1",
            rmf_status="queued",
            assignment=RmfAssignmentWindow(
                task_id="rmf-task-1",
                fleet_name="project1_pinky",
                robot_name="PK_02",
                start_ms=1,
                end_ms=2,
            ),
        )
    )
    worker = RmfGatewayWorker(
        gateway,
        transport,
        worker_id="worker",
        default_fleet_name="project1_pinky",
    )

    report = worker.run_once()

    assert transport.submissions[0][1]["request"]["robot_name"] == "PK_01"
    message_id, acceptance = gateway.acceptances[0]
    assert message_id == "message-1"
    assert acceptance.accepted is False
    assert acceptance.assigned_device_id is None
    assert acceptance.detail == (
        "ASSIGNMENT_MISMATCH: expected PK_01, RMF assigned PK_02"
    )
    assert report.accepted == 0
    assert report.rejected == 1
