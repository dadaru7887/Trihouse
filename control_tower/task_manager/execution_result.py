"""로봇 실행 사실을 결정적인 성공·실패 결과로 변환하는 계약."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class ActorRole(StrEnum):
    """작업 단계를 수행하거나 판단하는 주체 역할."""

    PINKY = "PINKY"
    OMX = "OMX"
    FMS = "FMS"


class AttemptState(StrEnum):
    """하나의 단계 실행 시도가 현재 어디까지 진행됐는지 나타낸다."""

    CREATED = "CREATED"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    RECONCILING = "RECONCILING"
    FINISHED = "FINISHED"


class AttemptOutcome(StrEnum):
    """종료된 단계 실행 시도의 결과."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
    CANCELLED = "CANCELLED"


class FailureDomain(StrEnum):
    """실패가 발생한 계층을 구분하는 안정적인 분류 값."""

    NONE = "NONE"
    ROBOT = "ROBOT"
    PERCEPTION = "PERCEPTION"
    NAVIGATION = "NAVIGATION"
    MANIPULATION = "MANIPULATION"
    SAFETY = "SAFETY"
    INTEGRATION = "INTEGRATION"
    OPERATOR = "OPERATOR"
    UNKNOWN = "UNKNOWN"


class DataQualityStatus(StrEnum):
    """실행 결과가 학습·판정에 사용 가능한 정도."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"


@dataclass(frozen=True)
class CompletionEvent:
    """Gate와 단계 진행에 필요한 최소 완료 이벤트."""

    event_id: str
    job_id: str
    job_step_id: str
    assignment_revision: int
    actor_role: ActorRole
    actor_id: str
    success: bool

    def __post_init__(self) -> None:
        if not all((self.event_id, self.job_id, self.job_step_id, self.actor_id)):
            raise ValueError("completion event identifiers are required")
        if self.assignment_revision < 0:
            raise ValueError("assignment revision cannot be negative")


@dataclass(frozen=True)
class Criterion:
    """성공 판정에 사용하는 한 가지 독립적인 관측 기준."""

    code: str
    passed: bool
    expected: Any = None
    observed: Any = None
    failure_reason_code: str = "CRITERION_FAILED"
    failure_domain: FailureDomain = FailureDomain.UNKNOWN
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("criterion code is required")


@dataclass(frozen=True)
class ExecutionFact:
    """장비 보고와 센서 검증에서 얻은 실행 시도의 구조화된 사실."""

    event_id: str
    job_id: str
    job_step_id: str
    assignment_revision: int
    actor_role: ActorRole
    actor_id: str
    command_uuid: str
    method_code: str
    command_outcome: AttemptOutcome
    reported_reason_code: str = ""
    failure_domain: FailureDomain = FailureDomain.NONE
    detail: str = ""
    criteria: tuple[Criterion, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    before_observation: Mapping[str, Any] = field(default_factory=dict)
    after_observation: Mapping[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    policy_name: str = ""
    policy_version: str = ""
    model_name: str = ""
    model_version: str = ""
    data_quality_status: DataQualityStatus = DataQualityStatus.COMPLETE
    required_criterion_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        identifiers = (
            self.event_id,
            self.job_id,
            self.job_step_id,
            self.actor_id,
            self.command_uuid,
            self.method_code,
        )
        if not all(identifiers):
            raise ValueError("execution fact identifiers and method code are required")
        if self.assignment_revision < 0:
            raise ValueError("assignment revision cannot be negative")


@dataclass(frozen=True)
class ExecutionOutcome:
    """관제·DB·학습 데이터가 공통으로 사용하는 최종 실행 결과."""

    success: bool
    outcome: AttemptOutcome
    outcome_reason_code: str
    method_code: str
    failure_domain: FailureDomain
    detail: str
    criteria: tuple[Criterion, ...]
    metrics: Mapping[str, Any]


def classify_execution(fact: ExecutionFact) -> ExecutionOutcome:
    """구조화된 사실만 사용해 동일 입력에 항상 동일 결과를 반환한다."""

    if fact.command_outcome is not AttemptOutcome.SUCCEEDED:
        reason_code = fact.reported_reason_code or f"COMMAND_{fact.command_outcome.value}"
        failure_domain = (
            fact.failure_domain
            if fact.failure_domain is not FailureDomain.NONE
            else FailureDomain.UNKNOWN
        )
        return ExecutionOutcome(
            success=False,
            outcome=fact.command_outcome,
            outcome_reason_code=reason_code,
            method_code=fact.method_code,
            failure_domain=failure_domain,
            detail=fact.detail,
            criteria=fact.criteria,
            metrics=fact.metrics,
        )

    observed_criterion_codes = {criterion.code for criterion in fact.criteria}
    missing_criteria = set(fact.required_criterion_codes).difference(
        observed_criterion_codes
    )
    if (
        fact.data_quality_status is not DataQualityStatus.COMPLETE
        or missing_criteria
    ):
        return ExecutionOutcome(
            success=False,
            outcome=AttemptOutcome.FAILED,
            outcome_reason_code="UNCLASSIFIED_RESULT",
            method_code=fact.method_code,
            failure_domain=FailureDomain.UNKNOWN,
            detail=fact.detail,
            criteria=fact.criteria,
            metrics=fact.metrics,
        )

    failed_criterion = next(
        (criterion for criterion in fact.criteria if not criterion.passed),
        None,
    )
    if failed_criterion is not None:
        return ExecutionOutcome(
            success=False,
            outcome=AttemptOutcome.FAILED,
            outcome_reason_code=failed_criterion.failure_reason_code,
            method_code=fact.method_code,
            failure_domain=failed_criterion.failure_domain,
            detail=failed_criterion.detail or fact.detail,
            criteria=fact.criteria,
            metrics=fact.metrics,
        )

    return ExecutionOutcome(
        success=True,
        outcome=AttemptOutcome.SUCCEEDED,
        outcome_reason_code="ALL_CRITERIA_PASSED",
        method_code=fact.method_code,
        failure_domain=FailureDomain.NONE,
        detail=fact.detail,
        criteria=fact.criteria,
        metrics=fact.metrics,
    )
