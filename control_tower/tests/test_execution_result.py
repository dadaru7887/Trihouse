"""구조화된 실행 사실을 학습 가능한 성공·실패 결과로 분류하는 테스트."""

from control_tower.task_manager.execution_result import (
    ActorRole,
    AttemptOutcome,
    Criterion,
    ExecutionFact,
    FailureDomain,
    classify_execution,
)


def _fact(**overrides: object) -> ExecutionFact:
    values: dict[str, object] = {
        "event_id": "event-1",
        "job_id": "job-1",
        "job_step_id": "step-1",
        "assignment_revision": 3,
        "actor_role": ActorRole.PINKY,
        "actor_id": "PK-01",
        "command_uuid": "command-1",
        "method_code": "RMF_NAVIGATE",
        "command_outcome": AttemptOutcome.SUCCEEDED,
        "reported_reason_code": "",
        "failure_domain": FailureDomain.NONE,
        "detail": "목표 waypoint 도착",
        "criteria": (
            Criterion(
                code="TARGET_REACHED",
                passed=True,
                expected="PACK-01",
                observed="PACK-01",
            ),
        ),
        "metrics": {"duration_s": 42.0},
        "before_observation": {"waypoint": "FROZEN-01"},
        "after_observation": {"waypoint": "PACK-01"},
        "evidence_refs": ("rosbag://run-1",),
        "policy_name": "dispatch_policy",
        "policy_version": "1.0",
        "model_name": "",
        "model_version": "",
        "data_quality_status": "VALID",
    }
    values.update(overrides)
    return ExecutionFact(**values)


def test_success_requires_command_success_and_every_criterion_to_pass() -> None:
    """판정 기준 하나를 무시하는 회귀가 성공 라벨을 만들지 못하게 한다."""
    outcome = classify_execution(_fact())

    assert outcome.success is True
    assert outcome.outcome is AttemptOutcome.SUCCEEDED
    assert outcome.outcome_reason_code == "ALL_CRITERIA_PASSED"
    assert outcome.method_code == "RMF_NAVIGATE"
    assert outcome.metrics == {"duration_s": 42.0}


def test_failed_criterion_supplies_deterministic_reason_and_failure_domain() -> None:
    """위치 불일치를 자유 텍스트가 아닌 고정 reason code로 분류한다."""
    outcome = classify_execution(
        _fact(
            criteria=(
                Criterion(
                    code="TARGET_REACHED",
                    passed=False,
                    expected="PACK-01",
                    observed="AISLE-02",
                    failure_reason_code="TARGET_NOT_REACHED",
                    failure_domain=FailureDomain.NAVIGATION,
                ),
            )
        )
    )

    assert outcome.success is False
    assert outcome.outcome is AttemptOutcome.FAILED
    assert outcome.outcome_reason_code == "TARGET_NOT_REACHED"
    assert outcome.failure_domain is FailureDomain.NAVIGATION


def test_reported_command_failure_preserves_structured_cause_without_detail() -> None:
    """상세 문장이 비어도 장비가 보고한 실패 코드와 영역은 유실되지 않는다."""
    outcome = classify_execution(
        _fact(
            command_outcome=AttemptOutcome.FAILED,
            reported_reason_code="LOCALIZATION_LOST",
            failure_domain=FailureDomain.NAVIGATION,
            detail="",
            criteria=(),
        )
    )

    assert outcome.success is False
    assert outcome.outcome is AttemptOutcome.FAILED
    assert outcome.outcome_reason_code == "LOCALIZATION_LOST"
    assert outcome.failure_domain is FailureDomain.NAVIGATION
    assert outcome.detail == ""


def test_cancelled_command_cannot_be_relabelled_as_failed_or_succeeded() -> None:
    """운영자 취소를 일반 실패로 뭉개는 회귀를 막는다."""
    outcome = classify_execution(
        _fact(
            command_outcome=AttemptOutcome.CANCELLED,
            reported_reason_code="OPERATOR_CANCELLED",
            failure_domain=FailureDomain.OPERATOR,
            criteria=(),
        )
    )

    assert outcome.success is False
    assert outcome.outcome is AttemptOutcome.CANCELLED
    assert outcome.outcome_reason_code == "OPERATOR_CANCELLED"
    assert outcome.failure_domain is FailureDomain.OPERATOR
