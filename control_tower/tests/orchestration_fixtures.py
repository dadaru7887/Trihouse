"""입고·출고 오케스트레이션 시나리오가 공유하는 실제 계약 fixture."""

from control_tower.task_manager.execution_result import (
    ActorRole,
    AttemptOutcome,
    CompletionEvent,
    ExecutionFact,
    FailureDomain,
)
from control_tower.task_manager.execution_store import TaskCommand


def successful_completion(
    step_id: str,
    role: ActorRole,
    actor_id: str,
    event_id: str,
    command: TaskCommand | None = None,
) -> tuple[CompletionEvent, ExecutionFact]:
    event = CompletionEvent(event_id, "job-1", step_id, 1, role, actor_id, True)
    fact = ExecutionFact(
        event_id=event_id,
        job_id="job-1",
        job_step_id=step_id,
        assignment_revision=1,
        actor_role=role,
        actor_id=actor_id,
        command_uuid=command.command_uuid if command else f"command-{event_id}",
        method_code=command.method_code if command else "HARDWARE_CONFIRMATION",
        command_outcome=AttemptOutcome.SUCCEEDED,
        failure_domain=FailureDomain.NONE,
    )
    return event, fact
