"""FMS 작업을 순서 있는 stage로 한 번씩만 진행하는 엔진."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class JobState(StrEnum):
    QUEUED = 'QUEUED'
    RUNNING = 'RUNNING'
    HELD = 'HELD'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'


@dataclass
class _Job:
    stages: tuple[str, ...]
    index: int = 0
    state: JobState = JobState.QUEUED
    result_ids: set[str] = field(default_factory=set)


class StageEngine:
    def __init__(self) -> None:
        self._jobs: dict[str, _Job] = {}

    def create(self, job_id: str, *, stages: tuple[str, ...]) -> None:
        if not job_id or not stages or len(stages) != len(set(stages)):
            raise ValueError('job ID and unique ordered stages are required')
        if job_id in self._jobs:
            raise ValueError('job already exists')
        self._jobs[job_id] = _Job(stages)

    def complete(self, job_id: str, *, stage_id: str, result_id: str) -> bool:
        job = self._job(job_id)
        if job.state in (JobState.HELD, JobState.COMPLETED, JobState.FAILED) or result_id in job.result_ids:
            return False
        if job.index >= len(job.stages) or job.stages[job.index] != stage_id:
            return False
        job.result_ids.add(result_id)
        job.index += 1
        job.state = JobState.COMPLETED if job.index == len(job.stages) else JobState.RUNNING
        return True

    def hold(self, job_id: str, *, reason: str) -> None:
        if not reason:
            raise ValueError('hold reason is required')
        job = self._job(job_id)
        if job.state == JobState.COMPLETED:
            raise ValueError('completed job cannot be held')
        job.state = JobState.HELD

    def resume(self, job_id: str) -> None:
        job = self._job(job_id)
        if job.state != JobState.HELD:
            raise ValueError('only held jobs can resume')
        job.state = JobState.RUNNING

    def current_stage(self, job_id: str) -> str | None:
        job = self._job(job_id)
        return None if job.index >= len(job.stages) else job.stages[job.index]

    def state_of(self, job_id: str) -> JobState:
        return self._job(job_id).state

    def _job(self, job_id: str) -> _Job:
        try:
            return self._jobs[job_id]
        except KeyError as error:
            raise ValueError(f'unknown job {job_id}') from error
