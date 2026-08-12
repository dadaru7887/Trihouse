"""SR08 단계·화물 상태와 할당 lineage를 이용한 안전 재할당 정책."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReassignmentContext:
    started: bool
    has_cargo: bool
    stages: tuple[str, ...]
    last_completed_stage: str | None

    def __post_init__(self) -> None:
        if not self.stages or any(not stage.strip() for stage in self.stages):
            raise ValueError("stages must contain non-empty values")
        if len(set(self.stages)) != len(self.stages):
            raise ValueError("stages must be unique")


@dataclass(frozen=True)
class ReassignmentDecision:
    action: str
    remaining_stages: tuple[str, ...]
    reason_code: str


def decide_reassignment(
    context: ReassignmentContext,
) -> ReassignmentDecision:
    """완료 단계를 반복하지 않으며 cargo가 있으면 자동 재할당을 막는다."""
    if context.has_cargo:
        return ReassignmentDecision(
            "HOLD", (), "ADMIN_INTERVENTION_REQUIRED"
        )
    if not context.started:
        return ReassignmentDecision(
            "RESUBMIT", context.stages, "REASSIGN_BEFORE_START"
        )
    if context.last_completed_stage not in context.stages:
        raise ValueError(
            "last_completed_stage must identify a stage in a started route"
        )
    completed_index = context.stages.index(context.last_completed_stage)
    remaining = context.stages[completed_index + 1 :]
    if not remaining:
        return ReassignmentDecision(
            "NO_ACTION", (), "ROUTE_ALREADY_COMPLETED"
        )
    return ReassignmentDecision(
        "RESUBMIT", remaining, "REASSIGN_REMAINING_STAGES"
    )


def accept_assignment_result(
    expected_revision: int,
    actual_revision: int,
    expected_task_id: str,
    actual_task_id: str,
) -> bool:
    """현재 assignment revision과 RMF task 결과만 수락한다."""
    if expected_revision < 0 or actual_revision < 0:
        raise ValueError("assignment revisions cannot be negative")
    if not expected_task_id.strip() or not actual_task_id.strip():
        return False
    return (
        actual_revision == expected_revision
        and actual_task_id == expected_task_id
    )
