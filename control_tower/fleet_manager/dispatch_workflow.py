"""FMS의 Pinky 배차와 작업 공간 예약 정책.

RMF는 실제 교통 실행을 맡고, 이 계층은 작업 전 공간을 예약하며 terminal event에서 해제한다.
"""

from dataclasses import dataclass
from typing import Mapping, Protocol

from .battery_policy import (
    BatteryAction,
    BatteryActionDecision,
    BatteryPolicySnapshot,
    BatteryPolicyState,
    WorkflowContext,
    decide_action,
)


class MeasurementWriter(Protocol):
    def write(self, stream: str, record: Mapping[str, object]) -> bool: ...


@dataclass(frozen=True)
class RobotSnapshot:
    robot_id: str
    ready: bool
    battery: float
    available_at_s: float
    cargo_present: bool
    battery_state: BatteryPolicyState = BatteryPolicyState.NORMAL
    battery_reason_code: str = "BATTERY_NORMAL"


@dataclass(frozen=True)
class TaskRequest:
    job_id: str
    priority: int
    requested_at_s: float
    workspace_id: str
    completed_steps: tuple[str, ...] = ()
    source_zone: str = ""
    destination_zone: str = ""
    finish_state_of_charge: float | None = None


@dataclass(frozen=True)
class Reassignment:
    assigned: bool
    robot_id: str = ''
    next_step: str = ''
    detail: str = ''


@dataclass(frozen=True)
class PostTaskDirective:
    robot_id: str
    mode: str
    reason_code: str


class DispatchWorkflow:
    def __init__(self, measurement_writer: MeasurementWriter | None = None) -> None:
        self._robots: dict[str, RobotSnapshot] = {}
        self._tasks: dict[str, TaskRequest] = {}
        self._assignments: dict[str, str] = {}
        self._workspace_owner: dict[str, str] = {}
        self._return_after_jobs: dict[str, str] = {}
        self._measurement_writer = measurement_writer

    def upsert_robot(self, robot: RobotSnapshot) -> None:
        self._robots[robot.robot_id] = robot

    def assign(self, task: TaskRequest) -> str:
        existing = self._assignments.get(task.job_id)
        if existing is not None:
            return existing
        owner = self._workspace_owner.get(task.workspace_id)
        if owner is not None and owner != task.job_id:
            raise ValueError(f'workspace {task.workspace_id} is reserved by {owner}')
        evaluations = [
            (robot, self._decision(robot, task))
            for robot in self._robots.values()
        ]
        candidates = sorted(
            (
                (robot, decision)
                for robot, decision in evaluations
                if self._is_assignable(robot, decision)
            ),
            key=lambda item: (item[0].available_at_s, item[0].robot_id),
        )
        if not candidates:
            for robot, decision in evaluations:
                self._record_decision(robot, task, decision, selected=False)
            raise ValueError('no assignable robot')
        robot, decision = candidates[0]
        for evaluated_robot, evaluated_decision in evaluations:
            self._record_decision(
                evaluated_robot,
                task,
                evaluated_decision,
                selected=evaluated_robot.robot_id == robot.robot_id,
            )
        self._tasks[task.job_id] = task; self._assignments[task.job_id] = robot.robot_id; self._workspace_owner[task.workspace_id] = task.job_id
        if decision.action == BatteryAction.COMPLETE_THEN_RETURN:
            self._return_after_jobs[task.job_id] = robot.robot_id
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
        self._return_after_jobs.pop(job_id, None)

    def complete(self, job_id: str) -> PostTaskDirective | None:
        return_robot_id = self._return_after_jobs.pop(job_id, None)
        self.cancel(job_id)
        if return_robot_id is None:
            return None
        return PostTaskDirective(
            robot_id=return_robot_id,
            mode='RETURN_TO_CHARGE',
            reason_code='FINAL_LOCAL_JOB_COMPLETED',
        )

    def reassign(self, job_id: str, *, failed_robot_id: str, cargo_present: bool) -> Reassignment:
        task = self._tasks.get(job_id)
        if task is None or self._assignments.get(job_id) != failed_robot_id:
            return Reassignment(False, next_step='MANUAL_INTERVENTION', detail='task assignment does not match failed robot')
        if cargo_present:
            return Reassignment(False, next_step='MANUAL_INTERVENTION', detail='cargo remains on failed robot')
        candidates = sorted(
            (
                (robot, decision)
                for robot in self._robots.values()
                for decision in (self._decision(robot, task),)
                if robot.robot_id != failed_robot_id
                and self._is_assignable(robot, decision)
            ),
            key=lambda item: (item[0].available_at_s, item[0].robot_id),
        )
        if not candidates:
            return Reassignment(False, next_step='WAIT_FOR_ROBOT', detail='no replacement robot')
        replacement, decision = candidates[0]
        self._record_decision(replacement, task, decision, selected=True)
        self._assignments[job_id] = replacement.robot_id
        next_step = self._next_step(task.completed_steps)
        return Reassignment(True, replacement.robot_id, next_step, 'reassigned')

    @staticmethod
    def _next_step(completed_steps: tuple[str, ...]) -> str:
        for step in ('PICK', 'LOAD', 'TRANSPORT', 'HANDOVER'):
            if step not in completed_steps and not (step == 'PICK' and 'PICKED' in completed_steps) and not (step == 'LOAD' and 'LOADED' in completed_steps):
                return step
        return 'HANDOVER'

    @staticmethod
    def _is_assignable(
        robot: RobotSnapshot, decision: BatteryActionDecision
    ) -> bool:
        if not robot.ready or robot.cargo_present:
            return False
        return decision.action in (
            BatteryAction.ALLOW_GENERAL_JOB,
            BatteryAction.ALLOW_LOCAL_JOB,
            BatteryAction.COMPLETE_THEN_RETURN,
        )

    @staticmethod
    def _decision(
        robot: RobotSnapshot, task: TaskRequest
    ) -> BatteryActionDecision:
        snapshot = BatteryPolicySnapshot(
            state=robot.battery_state,
            ready=robot.ready,
            percentage=robot.battery,
            reason_code=robot.battery_reason_code,
        )
        return decide_action(
            snapshot,
            WorkflowContext(
                source_zone=task.source_zone,
                destination_zone=task.destination_zone,
                finish_state_of_charge=task.finish_state_of_charge,
            ),
        )

    def _record_decision(
        self,
        robot: RobotSnapshot,
        task: TaskRequest,
        decision: BatteryActionDecision,
        *,
        selected: bool,
    ) -> None:
        if self._measurement_writer is None:
            return
        self._measurement_writer.write(
            "battery_policy_decisions",
            {
                "robot_id": robot.robot_id,
                "task_id": task.job_id,
                "state": robot.battery_state.value,
                "percentage": robot.battery,
                "ready": robot.ready,
                "cargo_present": robot.cargo_present,
                "source_zone": task.source_zone,
                "destination_zone": task.destination_zone,
                "finish_state_of_charge": task.finish_state_of_charge,
                "action": decision.action.value,
                "reason_code": decision.reason_code,
                "detail": decision.detail,
                "selected": selected,
            },
        )
