"""Gate·상태·실행 결과·다음 명령을 결합하는 오케스트레이터 테스트."""

from control_tower.task_manager.execution_result import (
    ActorRole,
    AttemptOutcome,
    CompletionEvent,
    ExecutionFact,
    FailureDomain,
)
from control_tower.task_manager.execution_store import InMemoryExecutionStore
from control_tower.task_manager.stage_engine import JobState, StageState
from control_tower.task_manager.task_orchestrator import StageSpec, TaskOrchestrator


def _specs() -> tuple[StageSpec, ...]:
    return (
        StageSpec(
            stage_id="READY_TO_TRANSFER",
            required_roles=frozenset({ActorRole.PINKY, ActorRole.OMX}),
        ),
        StageSpec(
            stage_id="TRANSFER",
            required_roles=frozenset({ActorRole.OMX}),
            command_kind="START_TRANSFER",
            target_role=ActorRole.OMX,
            method_code="OMX_HANDOVER",
        ),
    )


def _orchestrator() -> tuple[TaskOrchestrator, InMemoryExecutionStore]:
    store = InMemoryExecutionStore()
    orchestrator = TaskOrchestrator(store=store)
    orchestrator.create("job-1", stages=_specs())
    orchestrator.assign(
        "job-1",
        assignment_revision=1,
        actors={ActorRole.PINKY: "PK-01", ActorRole.OMX: "OMX-01"},
    )
    assert orchestrator.start("job-1", safety_approved=True).commands == ()
    return orchestrator, store


def _completion(
    event_id: str,
    role: ActorRole,
    actor_id: str,
    *,
    success: bool = True,
    revision: int = 1,
    step_id: str = "READY_TO_TRANSFER",
) -> tuple[CompletionEvent, ExecutionFact]:
    event = CompletionEvent(
        event_id=event_id,
        job_id="job-1",
        job_step_id=step_id,
        assignment_revision=revision,
        actor_role=role,
        actor_id=actor_id,
        success=success,
    )
    fact = ExecutionFact(
        event_id=event_id,
        job_id="job-1",
        job_step_id=step_id,
        assignment_revision=revision,
        actor_role=role,
        actor_id=actor_id,
        command_uuid=f"command-{event_id}",
        method_code="ARRIVAL_CONFIRMATION",
        command_outcome=(
            AttemptOutcome.SUCCEEDED if success else AttemptOutcome.FAILED
        ),
        reported_reason_code="" if success else "ARRIVAL_FAILED",
        failure_domain=FailureDomain.NONE if success else FailureDomain.NAVIGATION,
    )
    return event, fact


def test_second_success_completes_gate_and_creates_one_next_command() -> None:
    """두 장비 중 한쪽 완료만으로 다음 물리 명령이 생성되는 회귀를 막는다."""
    orchestrator, store = _orchestrator()
    pinky_event, pinky_fact = _completion("event-p", ActorRole.PINKY, "PK-01")
    omx_event, omx_fact = _completion("event-o", ActorRole.OMX, "OMX-01")

    first = orchestrator.record_completion(pinky_event, pinky_fact, safety_approved=True)
    second = orchestrator.record_completion(omx_event, omx_fact, safety_approved=True)

    assert first.commands == ()
    assert len(second.commands) == 1
    assert second.commands[0].command_kind == "START_TRANSFER"
    assert second.commands[0].actor_id == "OMX-01"
    assert orchestrator.stage_state("job-1", "READY_TO_TRANSFER") is StageState.SUCCEEDED
    assert orchestrator.stage_state("job-1", "TRANSFER") is StageState.RUNNING
    assert len(store.commands) == 1


def test_duplicate_completion_does_not_create_or_return_command_again() -> None:
    """완료 이벤트 재전송이 같은 명령을 외부 전송 대상으로 다시 반환하지 못하게 한다."""
    orchestrator, store = _orchestrator()
    pinky_event, pinky_fact = _completion("event-p", ActorRole.PINKY, "PK-01")
    omx_event, omx_fact = _completion("event-o", ActorRole.OMX, "OMX-01")
    orchestrator.record_completion(pinky_event, pinky_fact, safety_approved=True)
    orchestrator.record_completion(omx_event, omx_fact, safety_approved=True)

    duplicate = orchestrator.record_completion(
        omx_event,
        omx_fact,
        safety_approved=True,
    )

    assert duplicate.duplicate is True
    assert duplicate.commands == ()
    assert len(store.commands) == 1


def test_failed_execution_is_recorded_but_does_not_open_gate() -> None:
    """세밀한 실패 이력을 남기면서도 실패 완료로 Gate가 열리지 않게 한다."""
    orchestrator, store = _orchestrator()
    failed_event, failed_fact = _completion(
        "event-failed",
        ActorRole.PINKY,
        "PK-01",
        success=False,
    )
    omx_event, omx_fact = _completion("event-o", ActorRole.OMX, "OMX-01")

    failed = orchestrator.record_completion(
        failed_event,
        failed_fact,
        safety_approved=True,
    )
    peer = orchestrator.record_completion(omx_event, omx_fact, safety_approved=True)

    assert failed.reason_code == "EXECUTION_FAILED"
    assert peer.commands == ()
    assert store.executions[0].outcome.outcome_reason_code == "ARRIVAL_FAILED"
    assert store.executions[0].outcome.failure_domain is FailureDomain.NAVIGATION


def test_hold_defers_released_gate_command_until_safe_resume() -> None:
    """보류 중 모인 완료가 안전 확인 없이 후속 명령으로 바뀌지 않게 한다."""
    orchestrator, store = _orchestrator()
    pinky_event, pinky_fact = _completion("event-p", ActorRole.PINKY, "PK-01")
    omx_event, omx_fact = _completion("event-o", ActorRole.OMX, "OMX-01")
    orchestrator.record_completion(pinky_event, pinky_fact, safety_approved=True)
    orchestrator.hold("job-1", reason="PERSON_DETECTED")

    held = orchestrator.record_completion(
        omx_event,
        omx_fact,
        safety_approved=False,
    )
    unsafe_resume = orchestrator.resume("job-1", safety_approved=False)
    safe_resume = orchestrator.resume("job-1", safety_approved=True)

    assert held.commands == ()
    assert unsafe_resume.commands == ()
    assert orchestrator.job_state("job-1") is JobState.RUNNING
    assert len(safe_resume.commands) == 1
    assert len(store.commands) == 1


def test_reassignment_rejects_old_revision_and_uses_new_pinky() -> None:
    """재배정 전 Pinky 완료가 새 pairing의 완료로 섞이지 않게 한다."""
    orchestrator, _ = _orchestrator()
    old_event, old_fact = _completion("old-p", ActorRole.PINKY, "PK-01")
    orchestrator.record_completion(old_event, old_fact, safety_approved=True)
    orchestrator.reassign_pinky(
        "job-1",
        assignment_revision=2,
        pinky_id="PK-02",
    )

    old_omx, old_omx_fact = _completion("old-o", ActorRole.OMX, "OMX-01")
    stale = orchestrator.record_completion(
        old_omx,
        old_omx_fact,
        safety_approved=True,
    )
    new_pinky, new_pinky_fact = _completion(
        "new-p",
        ActorRole.PINKY,
        "PK-02",
        revision=2,
    )
    new_omx, new_omx_fact = _completion(
        "new-o",
        ActorRole.OMX,
        "OMX-01",
        revision=2,
    )
    orchestrator.record_completion(new_pinky, new_pinky_fact, safety_approved=True)
    released = orchestrator.record_completion(
        new_omx,
        new_omx_fact,
        safety_approved=True,
    )

    assert stale.reason_code == "STALE_ASSIGNMENT"
    assert len(released.commands) == 1


def test_safe_resume_starts_stage_that_was_held_before_initial_start() -> None:
    """최초 안전 미승인 후 승인돼도 작업이 ASSIGNED에 멈추는 회귀를 막는다."""
    store = InMemoryExecutionStore()
    orchestrator = TaskOrchestrator(store=store)
    orchestrator.create("job-1", stages=_specs())
    orchestrator.assign(
        "job-1",
        assignment_revision=1,
        actors={ActorRole.PINKY: "PK-01", ActorRole.OMX: "OMX-01"},
    )

    held = orchestrator.start("job-1", safety_approved=False)
    unsafe = orchestrator.resume("job-1", safety_approved=False)
    resumed = orchestrator.resume("job-1", safety_approved=True)

    assert held.reason_code == "SAFETY_NOT_APPROVED"
    assert unsafe.commands == ()
    assert resumed.reason_code == "STAGE_STARTED"
    assert orchestrator.job_state("job-1") is JobState.RUNNING
    assert orchestrator.stage_state("job-1", "READY_TO_TRANSFER") is StageState.RUNNING


def test_single_actor_completion_while_held_advances_once_after_safe_resume() -> None:
    """보류 중 저장한 단일 역할 완료가 중복 처리되어 영구 정체되는 회귀를 막는다."""
    store = InMemoryExecutionStore()
    orchestrator = TaskOrchestrator(store=store)
    orchestrator.create(
        "job-1",
        stages=(
            _specs()[0],
            _specs()[1],
            StageSpec(
                stage_id="VERIFY",
                required_roles=frozenset({ActorRole.FMS}),
                command_kind="VERIFY_TRANSFER",
                target_role=ActorRole.FMS,
                method_code="FMS_VERIFY",
            ),
        ),
    )
    orchestrator.assign(
        "job-1",
        assignment_revision=1,
        actors={
            ActorRole.PINKY: "PK-01",
            ActorRole.OMX: "OMX-01",
            ActorRole.FMS: "CONTROL_TOWER",
        },
    )
    orchestrator.start("job-1", safety_approved=True)
    pinky = _completion("ready-p", ActorRole.PINKY, "PK-01")
    omx = _completion("ready-o", ActorRole.OMX, "OMX-01")
    orchestrator.record_completion(*pinky, safety_approved=True)
    orchestrator.record_completion(*omx, safety_approved=True)
    orchestrator.hold("job-1", reason="PERSON_DETECTED")
    transfer = _completion(
        "transfer-done",
        ActorRole.OMX,
        "OMX-01",
        step_id="TRANSFER",
    )

    held_result = orchestrator.record_completion(
        *transfer,
        safety_approved=False,
    )
    resumed = orchestrator.resume("job-1", safety_approved=True)

    assert held_result.commands == ()
    assert len(resumed.commands) == 1
    assert resumed.commands[0].command_kind == "VERIFY_TRANSFER"
    assert orchestrator.stage_state("job-1", "TRANSFER") is StageState.SUCCEEDED
    assert orchestrator.stage_state("job-1", "VERIFY") is StageState.RUNNING
