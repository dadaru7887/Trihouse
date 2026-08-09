"""Gateway만 노출하는 메모리 기반 운영 read model.

HTTP/WebSocket adapter가 immutable view를 직렬화한다. UI는 DB·RMF·ROS를 직접 호출하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class RobotView:
    robot_id: str
    x: float
    y: float
    yaw: float
    battery_percent: float
    safety_state: str
    job_id: str
    stage: str
    error: str


@dataclass(frozen=True)
class JobView:
    job_id: str
    order_id: str
    item_ids: tuple[str, ...]
    robot_id: str
    stage: str
    state: str


@dataclass(frozen=True)
class IncidentView:
    incident_id: str
    camera_id: str
    location_id: str
    occurred_at_s: float
    acknowledged: bool


@dataclass(frozen=True)
class OperationsEvent:
    kind: str
    entity_id: str
    priority: int


@dataclass(frozen=True)
class OperationsSnapshot:
    robots: tuple[RobotView, ...]
    jobs: tuple[JobView, ...]
    incidents: tuple[IncidentView, ...]


class OperationsFeed:
    def __init__(self) -> None:
        self._robots: dict[str, RobotView] = {}
        self._jobs: dict[str, JobView] = {}
        self._incidents: dict[str, IncidentView] = {}
        self._events: list[OperationsEvent] = []

    def upsert_robot(self, robot: RobotView) -> None:
        self._robots[robot.robot_id] = robot
        self._events.append(OperationsEvent('ROBOT_UPDATED', robot.robot_id, 1))

    def upsert_job(self, job: JobView) -> None:
        self._jobs[job.job_id] = job
        self._events.append(OperationsEvent('JOB_UPDATED', job.job_id, 1))

    def open_incident(self, incident: IncidentView) -> None:
        self._incidents[incident.incident_id] = incident
        self._events.append(OperationsEvent('INCIDENT_OPEN', incident.incident_id, 100))

    def release_incident(self, incident_id: str, *, acknowledged_at_s: float) -> None:
        if acknowledged_at_s < 0:
            raise ValueError('acknowledgement timestamp must be non-negative')
        try:
            incident = self._incidents[incident_id]
        except KeyError as error:
            raise ValueError(f'unknown incident {incident_id}') from error
        self._incidents[incident_id] = replace(incident, acknowledged=True)
        self._events.append(OperationsEvent('INCIDENT_ACKNOWLEDGED', incident_id, 100))

    def snapshot(self) -> OperationsSnapshot:
        return OperationsSnapshot(
            tuple(sorted(self._robots.values(), key=lambda robot: robot.robot_id)),
            tuple(sorted(self._jobs.values(), key=lambda job: job.job_id)),
            tuple(sorted(self._incidents.values(), key=lambda incident: (not incident.acknowledged, incident.occurred_at_s), reverse=True)),
        )

    def drain_events(self) -> tuple[OperationsEvent, ...]:
        events = tuple(sorted(self._events, key=lambda event: -event.priority))
        self._events.clear()
        return events
