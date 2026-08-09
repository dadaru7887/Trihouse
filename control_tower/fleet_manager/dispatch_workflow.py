"""FMS의 Pinky 배차와 작업 공간 예약 정책.

RMF는 실제 교통 실행을 맡고, 이 계층은 작업 전 공간을 예약하며 terminal event에서 해제한다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RobotSnapshot:
    robot_id: str
    ready: bool
    battery: float
    available_at_s: float
    cargo_present: bool


@dataclass(frozen=True)
class TaskRequest:
    job_id: str
    priority: int
    requested_at_s: float
    workspace_id: str
    completed_steps: tuple[str, ...] = ()


@dataclass(frozen=True)
class Reassignment:
    assigned: bool
    robot_id: str = ''
    next_step: str = ''
    detail: str = ''


class DispatchWorkflow:
    def __init__(self) -> None:
        self._robots: dict[str, RobotSnapshot] = {}
        self._tasks: dict[str, TaskRequest] = {}
        self._assignments: dict[str, str] = {}
        self._workspace_owner: dict[str, str] = {}

    def upsert_robot(self, robot: RobotSnapshot) -> None:
        self._robots[robot.robot_id] = robot

    def assign(self, task: TaskRequest) -> str:
        existing = self._assignments.get(task.job_id)
        if existing is not None:
            return existing
        owner = self._workspace_owner.get(task.workspace_id)
        if owner is not None and owner != task.job_id:
            raise ValueError(f'workspace {task.workspace_id} is reserved by {owner}')
        candidates = sorted((robot for robot in self._robots.values() if robot.ready and not robot.cargo_present and robot.battery > 20), key=lambda robot: (robot.available_at_s, robot.robot_id))
        if not candidates:
            raise ValueError('no assignable robot')
        robot = candidates[0]
        self._tasks[task.job_id] = task; self._assignments[task.job_id] = robot.robot_id; self._workspace_owner[task.workspace_id] = task.job_id
        return robot.robot_id

    def schedule(self, tasks: list[TaskRequest]) -> dict[str, str]:
        """우선순위 후 접수 순서로 queue를 결정적으로 배차한다.

        로봇이나 작업 공간이 없으면 대기 상태로 남기고 terminal event 뒤 다시 시도한다.
        """
        scheduled: dict[str, str] = {}
        for task in sorted(tasks, key=lambda item: (-item.priority, item.requested_at_s, item.job_id)):
            try:
                scheduled[task.job_id] = self.assign(task)
            except ValueError:
                continue
        return scheduled

    def cancel(self, job_id: str) -> None:
        task = self._tasks.get(job_id)
        if task is not None and self._workspace_owner.get(task.workspace_id) == job_id:
            del self._workspace_owner[task.workspace_id]
        self._assignments.pop(job_id, None)

    def complete(self, job_id: str) -> None:
        self.cancel(job_id)

    def reassign(self, job_id: str, *, failed_robot_id: str, cargo_present: bool) -> Reassignment:
        task = self._tasks.get(job_id)
        if task is None or self._assignments.get(job_id) != failed_robot_id:
            return Reassignment(False, next_step='MANUAL_INTERVENTION', detail='task assignment does not match failed robot')
        if cargo_present:
            return Reassignment(False, next_step='MANUAL_INTERVENTION', detail='cargo remains on failed robot')
        candidates = sorted((robot for robot in self._robots.values() if robot.robot_id != failed_robot_id and robot.ready and not robot.cargo_present and robot.battery > 20), key=lambda robot: (robot.available_at_s, robot.robot_id))
        if not candidates:
            return Reassignment(False, next_step='WAIT_FOR_ROBOT', detail='no replacement robot')
        replacement = candidates[0]
        self._assignments[job_id] = replacement.robot_id
        next_step = self._next_step(task.completed_steps)
        return Reassignment(True, replacement.robot_id, next_step, 'reassigned')

    @staticmethod
    def _next_step(completed_steps: tuple[str, ...]) -> str:
        for step in ('PICK', 'LOAD', 'TRANSPORT', 'HANDOVER'):
            if step not in completed_steps and not (step == 'PICK' and 'PICKED' in completed_steps) and not (step == 'LOAD' and 'LOADED' in completed_steps):
                return step
        return 'HANDOVER'
