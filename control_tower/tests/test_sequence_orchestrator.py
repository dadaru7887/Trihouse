"""State-machine tests for the minimal FMS-backed outbound orchestrator."""

from __future__ import annotations

from dataclasses import dataclass

from control_tower.gateway.fms_client import (
    JobCreateRequest,
    JobCreateResponse,
    JobStepResponse,
    StepDispatchRequest,
    StepDispatchResponse,
)
from control_tower.task_manager.sequence_orchestrator import (
    SequenceOrchestrator,
    StepObjective,
)


@dataclass
class FakeGateway:
    create_response: JobCreateResponse

    def __post_init__(self) -> None:
        self.created: list[JobCreateRequest] = []
        self.dispatched: list[tuple[int, StepDispatchRequest]] = []

    def create_job(self, request: JobCreateRequest) -> JobCreateResponse:
        self.created.append(request)
        return self.create_response

    def dispatch_step(
        self,
        job_step_id: int,
        request: StepDispatchRequest,
    ) -> StepDispatchResponse:
        self.dispatched.append((job_step_id, request))
        return StepDispatchResponse(
            message_id=f"message-{len(self.dispatched)}",
            idempotency_key=request.idempotency_key,
            job_id=self.create_response.job_id,
            job_step_id=job_step_id,
            channel="rmf",
            message_type="rmf_dispatch",
            state="pending",
            payload={},
        )


def gateway_response() -> JobCreateResponse:
    specifications = (
        (100, 10, "navigate", "mobile", 11),
        (200, 20, "navigate", "mobile", 12),
        (300, 30, "load", "arm", 12),
        (400, 40, "navigate", "mobile", 13),
        (500, 50, "navigate", "mobile", 14),
        (600, 60, "handover", "fms", 14),
    )
    return JobCreateResponse(
        job_id=7,
        job_code="OUT-7",
        state="queued",
        steps=tuple(
            JobStepResponse(
                job_step_id=step_id,
                step_no=step_no,
                action_type=action,
                executor_type=executor,
                target_location_id=target,
                state="pending",
            )
            for step_id, step_no, action, executor, target in specifications
        ),
    )


def start_orchestrator() -> tuple[SequenceOrchestrator, FakeGateway]:
    gateway = FakeGateway(gateway_response())
    orchestrator = SequenceOrchestrator(gateway, actor="control-tower")
    orchestrator.create_outbound(
        job_code="OUT-7",
        source_location_id=10,
        locations={
            "inbound_waiting": 11,
            "OMX_01_station": 12,
            "narrow_waiting": 13,
            "outbound_waiting": 14,
        },
        mobile_device_id="PK_01",
    )
    return orchestrator, gateway


def test_create_outbound_persists_template_and_dispatches_only_step_10() -> None:
    """Creating a job must not pre-dispatch later physical work."""
    orchestrator, gateway = start_orchestrator()

    created = gateway.created[0]
    assert [(step.step_no, step.action_type, step.executor_type) for step in created.steps] == [
        (10, "navigate", "mobile"),
        (20, "navigate", "mobile"),
        (30, "load", "arm"),
        (40, "navigate", "mobile"),
        (50, "navigate", "mobile"),
        (60, "handover", "fms"),
    ]
    assert [step.target_location_id for step in created.steps] == [11, 12, 12, 13, 14, 14]
    assert [step.input for step in created.steps] == [
        {
            "source": "current",
            "target": "inbound_waiting",
            "source_location_id": 10,
            "target_location_id": 11,
            "sequence_id": "OUT-7",
            "segment_no": 10,
            "fleet_name": "project1_pinky",
        },
        {
            "source": "inbound_waiting",
            "target": "OMX_01_station",
            "source_location_id": 11,
            "target_location_id": 12,
            "sequence_id": "OUT-7",
            "segment_no": 20,
            "fleet_name": "project1_pinky",
        },
        {
            "source": "OMX_01_station",
            "target": "OMX_01_station",
            "source_location_id": 12,
            "target_location_id": 12,
            "sequence_id": "OUT-7",
            "segment_no": 30,
            "fleet_name": "project1_pinky",
        },
        {
            "source": "OMX_01_station",
            "target": "narrow_waiting",
            "source_location_id": 12,
            "target_location_id": 13,
            "sequence_id": "OUT-7",
            "segment_no": 40,
            "fleet_name": "project1_pinky",
        },
        {
            "source": "narrow_waiting",
            "target": "outbound_waiting",
            "source_location_id": 13,
            "target_location_id": 14,
            "sequence_id": "OUT-7",
            "segment_no": 50,
            "fleet_name": "project1_pinky",
        },
        {
            "source": "outbound_waiting",
            "target": "outbound_waiting",
            "source_location_id": 14,
            "target_location_id": 14,
            "sequence_id": "OUT-7",
            "segment_no": 60,
            "fleet_name": "project1_pinky",
        },
    ]
    assert [item[0] for item in gateway.dispatched] == [100]
    assert gateway.dispatched[0][1].assigned_device_id == "PK_01"
    assert orchestrator.current_step_id == 100


def test_only_current_terminal_success_unlocks_exactly_one_next_dispatch() -> None:
    """Running, failure, stale success, and duplicate success cannot advance sequence."""
    orchestrator, gateway = start_orchestrator()

    running = orchestrator.record_step_state(100, "running")
    failed = orchestrator.record_step_state(100, "failed")
    stale = orchestrator.record_step_state(999, "succeeded")
    advanced = orchestrator.record_step_state(100, "succeeded")
    duplicate = orchestrator.record_step_state(100, "succeeded")

    assert running.status == "waiting"
    assert failed.status == "retryable"
    assert stale.status == "unexpected_step"
    assert advanced.status == "dispatched"
    assert duplicate.status == "unexpected_step"
    assert [item[0] for item in gateway.dispatched] == [100, 200]
    assert orchestrator.current_step_id == 200


def test_same_objective_retry_dispatches_a_new_attempt_for_same_step() -> None:
    """A retry must not create or select a different persisted job step."""
    orchestrator, gateway = start_orchestrator()
    orchestrator.record_step_state(100, "failed")

    retried = orchestrator.retry_current(
        StepObjective(action_type="navigate", target_location_id=11)
    )

    assert retried.status == "dispatched"
    assert [item[0] for item in gateway.dispatched] == [100, 100]
    assert gateway.dispatched[0][1].idempotency_key != gateway.dispatched[1][1].idempotency_key
    assert gateway.dispatched[0][1].retry is False
    assert gateway.dispatched[1][1].retry is True
    assert len(gateway.created) == 1


def test_changed_objective_requires_replan_without_gateway_mutation() -> None:
    """P0 must stop instead of overwriting a failed objective or inventing recovery state."""
    orchestrator, gateway = start_orchestrator()
    orchestrator.record_step_state(100, "failed")

    result = orchestrator.retry_current(
        StepObjective(action_type="navigate", target_location_id=99)
    )

    assert result.status == "replan_required"
    assert result.reason_code == "OBJECTIVE_CHANGED"
    assert [item[0] for item in gateway.dispatched] == [100]
    assert orchestrator.current_step_id == 100


def test_replan_required_latches_stop_against_retry_and_late_success() -> None:
    """No later input may resume physical work before a durable recovery is installed."""
    orchestrator, gateway = start_orchestrator()
    original = StepObjective(action_type="navigate", target_location_id=11)
    orchestrator.record_step_state(100, "failed")
    orchestrator.retry_current(
        StepObjective(action_type="navigate", target_location_id=99)
    )

    retry = orchestrator.retry_current(original)
    late_success = orchestrator.record_step_state(100, "succeeded")

    assert retry.status == "replan_required"
    assert late_success.status == "replan_required"
    assert retry.reason_code == late_success.reason_code == "RECOVERY_STEP_REQUIRED"
    assert [item[0] for item in gateway.dispatched] == [100]
    assert orchestrator.current_step_id == 100


def test_cancelled_current_step_latches_replan_stop() -> None:
    """A late success after cancellation must not unlock the next physical step."""
    orchestrator, gateway = start_orchestrator()

    cancelled = orchestrator.record_step_state(100, "cancelled")
    late_success = orchestrator.record_step_state(100, "succeeded")

    assert cancelled.status == "replan_required"
    assert late_success.status == "replan_required"
    assert late_success.reason_code == "RECOVERY_STEP_REQUIRED"
    assert [item[0] for item in gateway.dispatched] == [100]
    assert orchestrator.current_step_id == 100
