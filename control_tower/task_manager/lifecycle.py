"""FMS 관리자 개입의 멱등·감사 가능한 작업 상태 전이."""

from dataclasses import dataclass, replace
from enum import StrEnum


class TaskState(StrEnum):
    QUEUED = 'QUEUED'
    ASSIGNED = 'ASSIGNED'
    HELD = 'HELD'
    ADMIN_INTERVENTION_REQUIRED = 'ADMIN_INTERVENTION_REQUIRED'
    CANCELLED = 'CANCELLED'


@dataclass(frozen=True)
class TaskRecord:
    job_id: str
    order_id: str
    robot_id: str
    state: TaskState
    completed_steps: tuple[str, ...] = ()
    next_step: str = 'PICK'
    reason: str = ''


class TaskLifecycle:
    """작업 진행 상태를 재고와 로봇 모션에서 분리한다.

    호출자는 반환 record/event를 DB에 저장한다. request ID는 REST/WebSocket 재시도의
    중복 실행을 막는다.
    """
    _STEP_ORDER = ('PICKED', 'LOADED', 'TRANSPORTED', 'HANDED_OVER')

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._request_results: dict[str, TaskRecord] = {}

    def create(self, job_id: str, *, order_id: str, robot_id: str) -> TaskRecord:
        if job_id in self._tasks:
            raise ValueError(f'duplicate job {job_id}')
        task = TaskRecord(job_id, order_id, robot_id, TaskState.QUEUED)
        self._tasks[job_id] = task
        return task

    def complete_step(self, job_id: str, step: str) -> TaskRecord:
        task = self._task(job_id)
        if step not in self._STEP_ORDER:
            raise ValueError(f'unknown step {step}')
        expected = self._STEP_ORDER[len(task.completed_steps)] if len(task.completed_steps) < len(self._STEP_ORDER) else None
        if step in task.completed_steps:
            return task
        if step != expected:
            raise ValueError(f'cannot complete {step} before {expected}')
        return self._save(replace(task, state=TaskState.ASSIGNED, completed_steps=task.completed_steps + (step,), next_step=self._next_step(task.completed_steps + (step,)), reason=''))

    def cancel(self, job_id: str, *, request_id: str, confirmed: bool) -> TaskRecord:
        task = self._task(job_id)
        if not confirmed:
            return task
        previous = self._request_results.get(request_id)
        if previous is not None:
            return previous
        result = self._save(replace(task, state=TaskState.CANCELLED, reason='cancelled by confirmed operator request'))
        self._request_results[request_id] = result
        return result

    def hold(self, job_id: str, *, reason: str, cargo_present: bool) -> TaskRecord:
        task = self._task(job_id)
        state = TaskState.ADMIN_INTERVENTION_REQUIRED if cargo_present else TaskState.HELD
        return self._save(replace(task, state=state, reason=reason))

    def reassign(self, job_id: str, *, request_id: str, confirmed: bool, robot_id: str) -> TaskRecord:
        task = self._task(job_id)
        if not confirmed:
            return task
        previous = self._request_results.get(request_id)
        if previous is not None:
            return previous
        if task.state != TaskState.HELD:
            return task
        result = self._save(replace(task, robot_id=robot_id, state=TaskState.ASSIGNED, next_step=self._next_step(task.completed_steps), reason=''))
        self._request_results[request_id] = result
        return result

    def release_emergency_hold(self, job_id: str, *, event_id: str, approved_by: str) -> TaskRecord:
        if not event_id or not approved_by:
            raise ValueError('event_id and approved_by are required')
        task = self._task(job_id)
        if task.state not in (TaskState.HELD, TaskState.ADMIN_INTERVENTION_REQUIRED):
            return task
        return self._save(replace(task, state=TaskState.HELD, reason='fresh FMS assignment required'))

    def _task(self, job_id: str) -> TaskRecord:
        try:
            return self._tasks[job_id]
        except KeyError as error:
            raise ValueError(f'unknown job {job_id}') from error

    def _save(self, task: TaskRecord) -> TaskRecord:
        self._tasks[task.job_id] = task
        return task

    @classmethod
    def _next_step(cls, completed_steps: tuple[str, ...]) -> str:
        for completed, next_step in zip(cls._STEP_ORDER, ('PICK', 'LOAD', 'TRANSPORT', 'HANDOVER')):
            if completed not in completed_steps:
                return next_step
        return 'COMPLETE'
