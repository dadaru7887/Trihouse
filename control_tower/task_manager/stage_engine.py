"""FMS 작업 상태와 순서 있는 단계 상태를 독립적으로 관리하는 엔진."""

from dataclasses import dataclass, field
from enum import StrEnum


class JobState(StrEnum):
    """Control Tower가 소유하는 업무 전체 수명주기."""

    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    HELD = "HELD"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StageState(StrEnum):
    """개별 업무 단계의 실행 상태."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


_TERMINAL_JOB_STATES = {
    JobState.COMPLETED,
    JobState.FAILED,
    JobState.CANCELLED,
}


@dataclass
class _Job:
    stages: tuple[str, ...]
    stage_states: dict[str, StageState]
    index: int = 0
    state: JobState = JobState.QUEUED
    resume_state: JobState | None = None
    result_ids: set[str] = field(default_factory=set)
    terminal_reason: str = ""


class StageEngine:
    """단계 순서와 현재 상태를 지키며 중복 결과를 한 번만 반영한다."""

    def __init__(self) -> None:
        self._jobs: dict[str, _Job] = {}

    def create(self, job_id: str, *, stages: tuple[str, ...]) -> None:
        if not job_id or not stages or len(stages) != len(set(stages)):
            raise ValueError("job ID and unique ordered stages are required")
        if job_id in self._jobs:
            raise ValueError("job already exists")
        self._jobs[job_id] = _Job(
            stages=stages,
            stage_states={stage: StageState.PENDING for stage in stages},
        )

    def assign(self, job_id: str) -> None:
        """대기 작업에 실행 주체 배정이 끝났음을 표시한다."""

        job = self._job(job_id)
        if job.state is not JobState.QUEUED:
            raise ValueError("only queued jobs can be assigned")
        job.state = JobState.ASSIGNED

    def start(self, job_id: str) -> str:
        """현재 PENDING 단계를 명시적으로 시작하고 단계 ID를 반환한다."""

        job = self._job(job_id)
        if job.state not in (JobState.ASSIGNED, JobState.RUNNING):
            raise ValueError("job must be assigned before a stage can start")
        stage_id = self.current_stage(job_id)
        if stage_id is None:
            raise ValueError("completed job has no stage to start")
        if job.stage_states[stage_id] is not StageState.PENDING:
            raise ValueError("current stage is not pending")
        job.stage_states[stage_id] = StageState.RUNNING
        job.state = JobState.RUNNING
        return stage_id

    def complete(self, job_id: str, *, stage_id: str, result_id: str) -> bool:
        """현재 실행 중인 단계의 새 완료 결과만 한 번 반영한다."""

        job = self._job(job_id)
        if (
            not result_id
            or job.state is not JobState.RUNNING
            or result_id in job.result_ids
            or self.current_stage(job_id) != stage_id
            or job.stage_states[stage_id] is not StageState.RUNNING
        ):
            return False
        job.result_ids.add(result_id)
        job.stage_states[stage_id] = StageState.SUCCEEDED
        job.index += 1
        if job.index == len(job.stages):
            job.state = JobState.COMPLETED
        return True

    def hold(self, job_id: str, *, reason: str) -> None:
        """현재 단계 상태를 바꾸지 않고 작업 명령 진행만 보류한다."""

        if not reason:
            raise ValueError("hold reason is required")
        job = self._job(job_id)
        if job.state in _TERMINAL_JOB_STATES:
            raise ValueError("terminal job cannot be held")
        if job.state is JobState.HELD:
            return
        job.resume_state = job.state
        job.state = JobState.HELD
        job.terminal_reason = reason

    def resume(self, job_id: str) -> None:
        """보류 직전 상태로 돌아가며 단계 진행 위치는 유지한다."""

        job = self._job(job_id)
        if job.state is not JobState.HELD or job.resume_state is None:
            raise ValueError("only held jobs can resume")
        job.state = job.resume_state
        job.resume_state = None
        job.terminal_reason = ""

    def fail(self, job_id: str, *, stage_id: str, reason: str) -> None:
        """현재 단계와 작업을 동일한 실패로 종료한다."""

        if not reason:
            raise ValueError("failure reason is required")
        job = self._job(job_id)
        if self.current_stage(job_id) != stage_id:
            raise ValueError("only the current stage can fail")
        if job.stage_states[stage_id] not in (StageState.PENDING, StageState.RUNNING):
            raise ValueError("terminal stage cannot fail again")
        job.stage_states[stage_id] = StageState.FAILED
        job.state = JobState.FAILED
        job.terminal_reason = reason

    def cancel(self, job_id: str) -> None:
        """현재 미완료 단계를 취소하고 작업을 종료한다."""

        job = self._job(job_id)
        if job.state in _TERMINAL_JOB_STATES:
            raise ValueError("terminal job cannot be cancelled again")
        stage_id = self.current_stage(job_id)
        if stage_id is not None:
            job.stage_states[stage_id] = StageState.CANCELLED
        job.state = JobState.CANCELLED
        job.resume_state = None

    def current_stage(self, job_id: str) -> str | None:
        job = self._job(job_id)
        return None if job.index >= len(job.stages) else job.stages[job.index]

    def stage_state(self, job_id: str, stage_id: str) -> StageState:
        job = self._job(job_id)
        try:
            return job.stage_states[stage_id]
        except KeyError as error:
            raise ValueError(f"unknown stage {stage_id}") from error

    def state_of(self, job_id: str) -> JobState:
        return self._job(job_id).state

    def _job(self, job_id: str) -> _Job:
        try:
            return self._jobs[job_id]
        except KeyError as error:
            raise ValueError(f"unknown job {job_id}") from error
