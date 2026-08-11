"""메모리 repository가 MySQL 유일성과 명령 fencing을 재현하는 테스트."""

from control_tower.task_manager.execution_result import (
    ActorRole,
    AttemptOutcome,
    CompletionEvent,
    ExecutionFact,
    FailureDomain,
    classify_execution,
)
from control_tower.task_manager.execution_store import InMemoryExecutionStore, TaskCommand


def _execution(event_id: str, command_uuid: str) -> tuple[CompletionEvent, ExecutionFact]:
    event = CompletionEvent(
        event_id,
        "job-1",
        "step-1",
        1,
        ActorRole.OMX,
        "OMX-01",
        True,
    )
    fact = ExecutionFact(
        event_id=event_id,
        job_id="job-1",
        job_step_id="step-1",
        assignment_revision=1,
        actor_role=ActorRole.OMX,
        actor_id="OMX-01",
        command_uuid=command_uuid,
        method_code="OMX_TRANSFER",
        command_outcome=AttemptOutcome.SUCCEEDED,
        failure_domain=FailureDomain.NONE,
    )
    return event, fact


def test_one_command_accepts_only_one_terminal_execution_even_with_new_event_id() -> None:
    """동시·재전송 결과가 한 command의 terminal attempt를 두 개 만들지 못하게 한다."""
    store = InMemoryExecutionStore()
    first_event, first_fact = _execution("event-1", "command-1")
    second_event, second_fact = _execution("event-2", "command-1")

    first = store.record_execution(
        first_event,
        first_fact,
        classify_execution(first_fact),
    )
    second = store.record_execution(
        second_event,
        second_fact,
        classify_execution(second_fact),
    )

    assert first is True
    assert second is False
    assert len(store.executions) == 1


def test_invalidated_command_is_removed_from_dispatch_eligibility() -> None:
    """취소·재배정된 revision 명령을 dispatcher가 active로 조회하지 못하게 한다."""
    store = InMemoryExecutionStore()
    command = TaskCommand(
        command_uuid="command-1",
        idempotency_key="job-1:step-1:1:OMX:TRANSFER",
        job_id="job-1",
        job_step_id="step-1",
        assignment_revision=1,
        actor_role="OMX",
        actor_id="OMX-01",
        command_kind="TRANSFER",
        method_code="OMX_TRANSFER",
    )
    store.save_command(command)

    invalidated = store.invalidate_commands("job-1", assignment_revision=1)

    assert invalidated == 1
    assert store.is_command_active("command-1") is False
