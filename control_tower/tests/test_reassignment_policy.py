"""SR08 재할당 안전 조건과 fencing 테스트."""

import pytest

from control_tower.fleet_manager.reassignment_policy import (
    ReassignmentContext,
    accept_assignment_result,
    decide_reassignment,
)


def test_before_start_reassigns_whole_route() -> None:
    """시작 전 장애에서 주문 일부만 새 Pinky에 전달되는 회귀를 막는다."""
    decision = decide_reassignment(
        ReassignmentContext(False, False, ("A", "B"), None)
    )

    assert decision.action == "RESUBMIT"
    assert decision.remaining_stages == ("A", "B")
    assert decision.reason_code == "REASSIGN_BEFORE_START"


def test_in_progress_without_cargo_starts_after_last_completed_stage() -> None:
    """재할당이 완료된 pick/transport 단계를 반복하는 회귀를 막는다."""
    decision = decide_reassignment(
        ReassignmentContext(True, False, ("A", "B", "C"), "A")
    )

    assert decision.action == "RESUBMIT"
    assert decision.remaining_stages == ("B", "C")


def test_in_progress_with_cargo_requires_admin() -> None:
    """고장 Pinky에 화물이 남은 상태에서 자동 재배차하는 회귀를 막는다."""
    decision = decide_reassignment(
        ReassignmentContext(True, True, ("A", "B"), "A")
    )

    assert decision.action == "HOLD"
    assert decision.remaining_stages == ()
    assert decision.reason_code == "ADMIN_INTERVENTION_REQUIRED"


def test_completed_route_does_not_create_an_empty_new_task() -> None:
    """마지막 단계 완료 후 빈 composed task를 제출하는 회귀를 막는다."""
    decision = decide_reassignment(
        ReassignmentContext(True, False, ("A", "B"), "B")
    )

    assert decision.action == "NO_ACTION"
    assert decision.reason_code == "ROUTE_ALREADY_COMPLETED"


def test_started_route_requires_known_last_completed_stage() -> None:
    """진행 위치를 추정해 완료 단계를 다시 수행하는 회귀를 막는다."""
    with pytest.raises(ValueError, match="last_completed_stage"):
        decide_reassignment(
            ReassignmentContext(True, False, ("A", "B"), "unknown")
        )


@pytest.mark.parametrize(
    ("actual_revision", "actual_task_id"),
    [(6, "task-1"), (7, "task-old")],
)
def test_stale_revision_or_task_result_is_rejected(
    actual_revision: int, actual_task_id: str
) -> None:
    """이전 Pinky/RMF 실행 결과가 새 할당을 완료 처리하는 회귀를 막는다."""
    assert (
        accept_assignment_result(
            expected_revision=7,
            actual_revision=actual_revision,
            expected_task_id="task-1",
            actual_task_id=actual_task_id,
        )
        is False
    )


def test_current_revision_and_task_result_is_accepted() -> None:
    """현재 실행 결과까지 fencing이 차단하는 회귀를 막는다."""
    assert accept_assignment_result(7, 7, "task-1", "task-1") is True
