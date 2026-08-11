"""완료 이벤트를 단계 진행과 멱등 후속 명령으로 연결하는 오케스트레이터."""

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from .execution_result import (
    ActorRole,
    CompletionEvent,
    ExecutionFact,
    classify_execution,
)
from .execution_store import ExecutionStore, TaskCommand
from .handover_gate import HandoverGate
from .stage_engine import JobState, StageEngine, StageState


@dataclass(frozen=True)
class StageSpec:
    """단계 완료 주체와 단계 시작 시 보낼 명령 계약."""

    stage_id: str
    required_roles: frozenset[ActorRole]
    command_kind: str = ""
    target_role: ActorRole | None = None
    method_code: str = ""

    def __post_init__(self) -> None:
        if not self.stage_id or not self.required_roles:
            raise ValueError("stage ID and required roles are required")
        command_fields = (self.command_kind, self.target_role, self.method_code)
        if any(command_fields) and not all(command_fields):
            raise ValueError("command kind, target role, and method code belong together")


@dataclass(frozen=True)
class OrchestrationResult:
    """이벤트 처리 결과와 이번 호출에서 새로 생성된 명령."""

    accepted: bool
    duplicate: bool = False
    commands: tuple[TaskCommand, ...] = ()
    reason_code: str = ""


@dataclass
class _JobPlan:
    stages: tuple[StageSpec, ...]
    assignment_revision: int = -1
    actors: dict[ActorRole, str] | None = None
    deferred_result_id: str = ""


class TaskOrchestrator:
    """StageEngine과 단순 Gate를 결합하되 각 구성요소의 책임을 유지한다."""

    def __init__(
        self,
        *,
        store: ExecutionStore,
        stages: StageEngine | None = None,
        gate: HandoverGate | None = None,
    ) -> None:
        self._store = store
        self._stages = stages or StageEngine()
        self._gate = gate or HandoverGate()
        self._plans: dict[str, _JobPlan] = {}

    def create(self, job_id: str, *, stages: tuple[StageSpec, ...]) -> None:
        if not stages or len({stage.stage_id for stage in stages}) != len(stages):
            raise ValueError("unique ordered stage specifications are required")
        self._stages.create(job_id, stages=tuple(stage.stage_id for stage in stages))
        self._plans[job_id] = _JobPlan(stages=stages)

    def assign(
        self,
        job_id: str,
        *,
        assignment_revision: int,
        actors: dict[ActorRole, str],
    ) -> None:
        plan = self._plan(job_id)
        required = set().union(*(stage.required_roles for stage in plan.stages))
        missing = required.difference(actors)
        if missing or any(not actors[role] for role in required):
            raise ValueError("every required role needs an assigned actor")
        if assignment_revision < 0:
            raise ValueError("assignment revision cannot be negative")
        plan.assignment_revision = assignment_revision
        plan.actors = dict(actors)
        self._stages.assign(job_id)

    def start(self, job_id: str, *, safety_approved: bool) -> OrchestrationResult:
        if not safety_approved:
            self._stages.hold(job_id, reason="SAFETY_NOT_APPROVED")
            return OrchestrationResult(False, reason_code="SAFETY_NOT_APPROVED")
        commands = self._start_current(job_id)
        return OrchestrationResult(True, commands=commands, reason_code="STAGE_STARTED")

    def record_completion(
        self,
        event: CompletionEvent,
        fact: ExecutionFact,
        *,
        safety_approved: bool,
    ) -> OrchestrationResult:
        self._validate_same_execution(event, fact)
        outcome = classify_execution(fact)
        if outcome.success != event.success:
            raise ValueError("completion success must match classified execution outcome")
        if not self._store.record_execution(event, fact, outcome):
            return OrchestrationResult(
                False,
                duplicate=True,
                reason_code="DUPLICATE_EVENT",
            )

        plan = self._plan(event.job_id)
        stage = self._current_spec(event.job_id)
        if stage is None or event.job_step_id != stage.stage_id:
            return OrchestrationResult(False, reason_code="UNEXPECTED_STEP")
        if event.assignment_revision != plan.assignment_revision:
            return OrchestrationResult(False, reason_code="STALE_ASSIGNMENT")
        if plan.actors is None or plan.actors.get(event.actor_role) != event.actor_id:
            return OrchestrationResult(False, reason_code="UNEXPECTED_ACTOR")

        if self._is_gate(stage):
            decision = self._gate.record(event)
            if not decision.released:
                return OrchestrationResult(
                    accepted=decision.accepted or not event.success,
                    duplicate=decision.duplicate,
                    reason_code=decision.reason_code,
                )
            if self._stages.state_of(event.job_id) is JobState.HELD or not safety_approved:
                if self._stages.state_of(event.job_id) is not JobState.HELD:
                    self._stages.hold(event.job_id, reason="SAFETY_NOT_APPROVED")
                plan.deferred_result_id = event.event_id
                return OrchestrationResult(True, reason_code="GATE_RELEASED_DEFERRED")
            commands = self._complete_and_start_next(event.job_id, event.event_id)
            return OrchestrationResult(
                True,
                commands=commands,
                reason_code="GATE_RELEASED",
            )

        if not event.success:
            return OrchestrationResult(True, reason_code="EXECUTION_FAILED")
        if event.actor_role not in stage.required_roles:
            return OrchestrationResult(False, reason_code="UNEXPECTED_ACTOR_ROLE")
        if self._stages.state_of(event.job_id) is JobState.HELD or not safety_approved:
            if self._stages.state_of(event.job_id) is not JobState.HELD:
                self._stages.hold(event.job_id, reason="SAFETY_NOT_APPROVED")
            if not plan.deferred_result_id:
                plan.deferred_result_id = event.event_id
            return OrchestrationResult(True, reason_code="COMPLETION_DEFERRED")
        commands = self._complete_and_start_next(event.job_id, event.event_id)
        return OrchestrationResult(True, commands=commands, reason_code="STEP_COMPLETED")

    def hold(self, job_id: str, *, reason: str) -> None:
        self._stages.hold(job_id, reason=reason)

    def resume(self, job_id: str, *, safety_approved: bool) -> OrchestrationResult:
        if not safety_approved:
            return OrchestrationResult(False, reason_code="SAFETY_NOT_APPROVED")
        plan = self._plan(job_id)
        self._stages.resume(job_id)
        if not plan.deferred_result_id:
            if self._stages.state_of(job_id) is JobState.ASSIGNED:
                commands = self._start_current(job_id)
                return OrchestrationResult(
                    True,
                    commands=commands,
                    reason_code="STAGE_STARTED",
                )
            return OrchestrationResult(True, reason_code="JOB_RESUMED")
        result_id = plan.deferred_result_id
        plan.deferred_result_id = ""
        commands = self._complete_and_start_next(job_id, result_id)
        return OrchestrationResult(
            True,
            commands=commands,
            reason_code="DEFERRED_GATE_RELEASED",
        )

    def reassign_pinky(
        self,
        job_id: str,
        *,
        assignment_revision: int,
        pinky_id: str,
    ) -> None:
        plan = self._plan(job_id)
        if plan.actors is None:
            raise ValueError("job must be assigned before reassignment")
        if assignment_revision <= plan.assignment_revision:
            raise ValueError("reassignment revision must increase")
        plan.assignment_revision = assignment_revision
        plan.actors[ActorRole.PINKY] = pinky_id
        plan.deferred_result_id = ""
        stage = self._current_spec(job_id)
        if stage is not None and self._is_gate(stage):
            self._gate.reassign_pinky(
                job_id,
                assignment_revision=assignment_revision,
                pinky_id=pinky_id,
            )

    def cancel(self, job_id: str) -> None:
        self._gate.cancel(job_id)
        self._stages.cancel(job_id)

    def job_state(self, job_id: str) -> JobState:
        return self._stages.state_of(job_id)

    def stage_state(self, job_id: str, stage_id: str) -> StageState:
        return self._stages.stage_state(job_id, stage_id)

    def _start_current(self, job_id: str) -> tuple[TaskCommand, ...]:
        stage_id = self._stages.start(job_id)
        stage = self._spec(job_id, stage_id)
        plan = self._plan(job_id)
        assert plan.actors is not None
        if self._is_gate(stage):
            self._gate.expect(
                job_id,
                job_step_id=stage.stage_id,
                assignment_revision=plan.assignment_revision,
                pinky_id=plan.actors[ActorRole.PINKY],
                omx_id=plan.actors[ActorRole.OMX],
            )
            return ()
        command = self._new_command(job_id, stage)
        return (command,) if command is not None else ()

    def _complete_and_start_next(
        self,
        job_id: str,
        result_id: str,
    ) -> tuple[TaskCommand, ...]:
        current = self._stages.current_stage(job_id)
        if current is None or not self._stages.complete(
            job_id,
            stage_id=current,
            result_id=result_id,
        ):
            return ()
        if self._stages.state_of(job_id) is JobState.COMPLETED:
            return ()
        return self._start_current(job_id)

    def _new_command(self, job_id: str, stage: StageSpec) -> TaskCommand | None:
        if not stage.command_kind or stage.target_role is None:
            return None
        plan = self._plan(job_id)
        assert plan.actors is not None
        actor_id = plan.actors[stage.target_role]
        idempotency_key = ":".join(
            (
                job_id,
                stage.stage_id,
                str(plan.assignment_revision),
                stage.target_role.value,
                stage.command_kind,
            )
        )
        command = TaskCommand(
            command_uuid=str(uuid5(NAMESPACE_URL, idempotency_key)),
            idempotency_key=idempotency_key,
            job_id=job_id,
            job_step_id=stage.stage_id,
            assignment_revision=plan.assignment_revision,
            actor_role=stage.target_role.value,
            actor_id=actor_id,
            command_kind=stage.command_kind,
            method_code=stage.method_code,
        )
        return command if self._store.save_command(command) else None

    def _current_spec(self, job_id: str) -> StageSpec | None:
        stage_id = self._stages.current_stage(job_id)
        return None if stage_id is None else self._spec(job_id, stage_id)

    def _spec(self, job_id: str, stage_id: str) -> StageSpec:
        return next(
            stage for stage in self._plan(job_id).stages if stage.stage_id == stage_id
        )

    @staticmethod
    def _is_gate(stage: StageSpec) -> bool:
        return stage.required_roles == frozenset({ActorRole.PINKY, ActorRole.OMX})

    @staticmethod
    def _validate_same_execution(event: CompletionEvent, fact: ExecutionFact) -> None:
        event_identity = (
            event.event_id,
            event.job_id,
            event.job_step_id,
            event.assignment_revision,
            event.actor_role,
            event.actor_id,
        )
        fact_identity = (
            fact.event_id,
            fact.job_id,
            fact.job_step_id,
            fact.assignment_revision,
            fact.actor_role,
            fact.actor_id,
        )
        if event_identity != fact_identity:
            raise ValueError("completion event and execution fact must describe the same execution")

    def _plan(self, job_id: str) -> _JobPlan:
        try:
            return self._plans[job_id]
        except KeyError as error:
            raise ValueError(f"unknown orchestration job {job_id}") from error
