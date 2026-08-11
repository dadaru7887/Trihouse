"""현재 배정의 Pinky·OMX 완료를 한 번만 결합하는 Gate 테스트."""

from control_tower.task_manager.execution_result import ActorRole, CompletionEvent
from control_tower.task_manager.handover_gate import HandoverGate


def _event(
    event_id: str,
    role: ActorRole,
    actor_id: str,
    *,
    success: bool = True,
    step_id: str = "step-1",
    revision: int = 1,
) -> CompletionEvent:
    return CompletionEvent(
        event_id=event_id,
        job_id="job-1",
        job_step_id=step_id,
        assignment_revision=revision,
        actor_role=role,
        actor_id=actor_id,
        success=success,
    )


def _gate() -> HandoverGate:
    gate = HandoverGate()
    gate.expect(
        "job-1",
        job_step_id="step-1",
        assignment_revision=1,
        pinky_id="PK-01",
        omx_id="OMX-01",
    )
    return gate


def test_releases_only_when_both_expected_robots_report_success() -> None:
    """한 장비 완료만으로 인계 후속 명령이 시작되는 회귀를 막는다."""
    gate = _gate()

    pinky = gate.record(_event("event-p", ActorRole.PINKY, "PK-01"))
    omx = gate.record(_event("event-o", ActorRole.OMX, "OMX-01"))

    assert pinky.accepted is True
    assert pinky.released is False
    assert omx.accepted is True
    assert omx.released is True


def test_duplicate_event_never_releases_gate_twice() -> None:
    """재전송된 완료 이벤트가 물리 명령을 중복 생성하지 못하게 한다."""
    gate = _gate()
    gate.record(_event("event-p", ActorRole.PINKY, "PK-01"))
    gate.record(_event("event-o", ActorRole.OMX, "OMX-01"))

    duplicate = gate.record(_event("event-o", ActorRole.OMX, "OMX-01"))

    assert duplicate.accepted is False
    assert duplicate.duplicate is True
    assert duplicate.released is False
    assert duplicate.reason_code == "DUPLICATE_EVENT"


def test_failure_stale_revision_and_foreign_actor_do_not_open_gate() -> None:
    """실패·과거 배정·다른 장비의 이벤트를 현재 완료로 오인하지 않는다."""
    gate = _gate()

    failed = gate.record(
        _event("failed", ActorRole.PINKY, "PK-01", success=False)
    )
    stale = gate.record(
        _event("stale", ActorRole.PINKY, "PK-01", revision=0)
    )
    foreign = gate.record(
        _event("foreign", ActorRole.PINKY, "PK-02")
    )
    omx = gate.record(_event("event-o", ActorRole.OMX, "OMX-01"))

    assert failed.reason_code == "EXECUTION_FAILED"
    assert stale.reason_code == "STALE_ASSIGNMENT"
    assert foreign.reason_code == "UNEXPECTED_ACTOR"
    assert omx.released is False


def test_reassignment_clears_old_completions_and_requires_new_revision() -> None:
    """이전 Pinky 완료가 재배정된 pairing에 남는 회귀를 막는다."""
    gate = _gate()
    gate.record(_event("old-p", ActorRole.PINKY, "PK-01"))
    gate.reassign_pinky(
        "job-1",
        assignment_revision=2,
        pinky_id="PK-02",
    )

    old_omx = gate.record(
        _event("old-o", ActorRole.OMX, "OMX-01", revision=1)
    )
    new_omx = gate.record(
        _event("new-o", ActorRole.OMX, "OMX-01", revision=2)
    )
    new_pinky = gate.record(
        _event("new-p", ActorRole.PINKY, "PK-02", revision=2)
    )

    assert old_omx.reason_code == "STALE_ASSIGNMENT"
    assert new_omx.released is False
    assert new_pinky.released is True


def test_cancel_removes_gate_authority() -> None:
    """취소된 작업의 지연 이벤트가 후속 명령 권한을 되살리지 못하게 한다."""
    gate = _gate()
    gate.cancel("job-1")

    decision = gate.record(_event("late", ActorRole.PINKY, "PK-01"))

    assert decision.accepted is False
    assert decision.released is False
    assert decision.reason_code == "UNKNOWN_GATE"
