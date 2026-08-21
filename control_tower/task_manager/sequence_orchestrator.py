"""Minimal ordered outbound orchestration through the FMS Gateway only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from control_tower.gateway.fms_client import (
    FMSGatewayClient,
    JobCreateRequest,
    JobCreateResponse,
    JobStepCreateRequest,
    StepDispatchRequest,
    StepDispatchResponse,
)

from .outbound_planner import OutboundPlan
from .outbound_sequence import outbound_segment_template, planned_outbound_steps


@dataclass(frozen=True)
class StepObjective:
    """Identity of work that may be retried without creating a recovery step."""

    action_type: str
    target_location_id: int | None


@dataclass(frozen=True)
class SequenceResult:
    status: str
    reason_code: str = ""
    dispatch: StepDispatchResponse | None = None


class SequenceOrchestrator:
    """Unlock the next persisted step only after current terminal success."""

    def __init__(self, gateway: FMSGatewayClient, *, actor: str) -> None:
        self._gateway = gateway
        self._actor = actor
        self._job: JobCreateResponse | None = None
        self._objectives: dict[int, StepObjective] = {}
        self._assigned_devices: dict[int, str | None] = {}
        self._current_index = -1
        self._current_state = ""
        self._dispatch_counts: dict[int, int] = {}

    @staticmethod
    def planned_step_requests(
        plan: OutboundPlan,
        omx_by_temperature_zone: Mapping[str, str],
    ) -> tuple[JobStepCreateRequest, ...]:
        """Translate a product plan without assigning Pinky or OMX hardware."""
        return tuple(
            JobStepCreateRequest(
                step_no=step.step_no,
                action_type=step.action_type,
                executor_type=step.executor_type,
                target_location_id=step.target_location_id,
                input=dict(step.input),
            )
            for step in planned_outbound_steps(plan, omx_by_temperature_zone)
        )

    @property
    def current_step_id(self) -> int | None:
        if self._job is None or self._current_index not in range(len(self._job.steps)):
            return None
        return self._job.steps[self._current_index].job_step_id

    def create_outbound(
        self,
        *,
        job_code: str,
        source_location_id: int,
        locations: Mapping[str, int],
        mobile_device_id: str,
        fleet_name: str = "project1_pinky",
        priority: str = "normal",
        requested_by: str | None = None,
        external_reference: str | None = None,
        context: dict[str, object] | None = None,
    ) -> SequenceResult:
        if self._job is not None:
            raise RuntimeError("an orchestrator instance owns exactly one outbound job")
        template = outbound_segment_template()
        required_locations = {step.target for step in template}.difference({"current"})
        missing = required_locations.difference(locations)
        if missing:
            raise ValueError(f"missing outbound locations: {', '.join(sorted(missing))}")
        steps = tuple(
            JobStepCreateRequest(
                step_no=step.step_no,
                action_type=step.action_type,
                executor_type=step.executor_type,
                target_location_id=locations[step.target],
                input={
                    "source": step.source,
                    "target": step.target,
                    "source_location_id": (
                        source_location_id
                        if step.source == "current"
                        else locations[step.source]
                    ),
                    "target_location_id": locations[step.target],
                    "sequence_id": job_code,
                    "segment_no": step.step_no,
                    "fleet_name": fleet_name,
                },
            )
            for step in template
        )
        created = self._gateway.create_job(
            JobCreateRequest(
                job_code=job_code,
                operation_type="outbound",
                priority=priority,
                requested_by=requested_by,
                external_reference=external_reference,
                source_location_id=source_location_id,
                destination_location_id=locations["outbound_waiting"],
                context=dict(context or {}),
                steps=steps,
            )
        )
        self._bind_created_job(created, steps, template, mobile_device_id)
        self._current_index = 0
        self._current_state = "pending"
        return self._dispatch_current()

    def record_step_state(self, job_step_id: int, state: str) -> SequenceResult:
        if job_step_id != self.current_step_id:
            return SequenceResult("unexpected_step", "NOT_CURRENT_STEP")
        if self._current_state == "replan_required":
            return SequenceResult("replan_required", "RECOVERY_STEP_REQUIRED")
        normalized = state.lower()
        if normalized == "succeeded":
            self._current_index += 1
            if self._job is not None and self._current_index == len(self._job.steps):
                self._current_state = "succeeded"
                return SequenceResult("completed")
            self._current_state = "pending"
            return self._dispatch_current()
        if normalized == "failed":
            self._current_state = normalized
            return SequenceResult("retryable", "CURRENT_STEP_FAILED")
        if normalized == "cancelled":
            self._current_state = "replan_required"
            return SequenceResult("replan_required", "CURRENT_STEP_CANCELLED")
        self._current_state = normalized
        return SequenceResult("waiting")

    def retry_current(self, objective: StepObjective) -> SequenceResult:
        step_id = self.current_step_id
        if self._current_state == "replan_required":
            return SequenceResult("replan_required", "RECOVERY_STEP_REQUIRED")
        if step_id is None or self._current_state != "failed":
            return SequenceResult("not_retryable", "CURRENT_STEP_NOT_FAILED")
        if objective != self._objectives[step_id]:
            self._current_state = "replan_required"
            return SequenceResult("replan_required", "OBJECTIVE_CHANGED")
        result = self._dispatch_current(retry=True)
        self._current_state = "pending"
        return result

    def _dispatch_current(self, *, retry: bool = False) -> SequenceResult:
        assert self._job is not None
        step_id = self.current_step_id
        assert step_id is not None
        attempt_no = self._dispatch_counts.get(step_id, 0) + 1
        self._dispatch_counts[step_id] = attempt_no
        dispatch = self._gateway.dispatch_step(
            step_id,
            StepDispatchRequest(
                idempotency_key=(
                    f"control-tower-job-{self._job.job_id}-step-{step_id}-attempt-{attempt_no}"
                ),
                actor=self._actor,
                assigned_device_id=self._assigned_devices[step_id],
                retry=retry,
            ),
        )
        return SequenceResult("dispatched", dispatch=dispatch)

    def _bind_created_job(
        self,
        created: JobCreateResponse,
        requests: tuple[JobStepCreateRequest, ...],
        template: tuple[object, ...],
        mobile_device_id: str,
    ) -> None:
        if tuple(step.step_no for step in created.steps) != tuple(
            step.step_no for step in requests
        ):
            raise ValueError("FMS Gateway returned a different ordered step sequence")
        self._job = created
        for response, request, source in zip(created.steps, requests, template, strict=True):
            self._objectives[response.job_step_id] = StepObjective(
                request.action_type,
                request.target_location_id,
            )
            executor_type = getattr(source, "executor_type")
            assigned_device_id = getattr(source, "assigned_device_id")
            if executor_type == "mobile":
                assigned_device_id = mobile_device_id
            self._assigned_devices[response.job_step_id] = assigned_device_id
