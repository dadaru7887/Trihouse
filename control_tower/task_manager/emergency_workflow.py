"""비상 구역과 해제 후 복귀를 FMS 권한으로 결정하는 정책.

RMF는 임시 구역을 받고, 즉시 물리 정지는 Pinky Safety Supervisor가 독립 수행한다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryAction:
    robot_id: str
    action: str
    job_id: str


@dataclass
class _AffectedRobot:
    robot_id: str
    job_id: str
    cargo_present: bool


@dataclass
class _Incident:
    polygon: tuple[tuple[float, float], ...]
    active: bool = True
    affected: list[_AffectedRobot] | None = None

    def __post_init__(self) -> None:
        if self.affected is None:
            self.affected = []


class EmergencyWorkflow:
    def __init__(self) -> None:
        self._incidents: dict[str, _Incident] = {}

    def open(self, incident_id: str, *, polygon: tuple[tuple[float, float], ...]) -> None:
        if not incident_id or len(polygon) < 3:
            raise ValueError('incident ID and a polygon are required')
        if incident_id in self._incidents:
            raise ValueError('incident already exists')
        self._incidents[incident_id] = _Incident(polygon)

    def blocks_assignment(self, incident_id: str, *, target_xy: tuple[float, float]) -> bool:
        incident = self._incident(incident_id)
        return incident.active and self._inside_polygon(target_xy, incident.polygon)

    def affect_robot(self, incident_id: str, *, robot_id: str, job_id: str, cargo_present: bool) -> None:
        incident = self._incident(incident_id)
        if not incident.active:
            raise ValueError('cannot add a robot after incident release')
        if any(robot.robot_id == robot_id for robot in incident.affected or []):
            return
        incident.affected.append(_AffectedRobot(robot_id, job_id, cargo_present))

    def release(self, incident_id: str, *, operator_id: str) -> tuple[RecoveryAction, ...]:
        if not operator_id:
            raise ValueError('identified operator approval is required')
        incident = self._incident(incident_id)
        if not incident.active:
            return ()
        incident.active = False
        return tuple(
            RecoveryAction(robot.robot_id, 'ADMIN_INTERVENTION_REQUIRED' if robot.cargo_present else 'RETURN_AND_HEALTH_CHECK', robot.job_id)
            for robot in incident.affected or []
        )

    def _incident(self, incident_id: str) -> _Incident:
        try:
            return self._incidents[incident_id]
        except KeyError as error:
            raise ValueError(f'unknown incident {incident_id}') from error

    @staticmethod
    def _inside_polygon(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> bool:
        x, y = point
        inside = False
        previous_x, previous_y = polygon[-1]
        for current_x, current_y in polygon:
            crosses = (current_y > y) != (previous_y > y)
            if crosses and x < (previous_x - current_x) * (y - current_y) / (previous_y - current_y) + current_x:
                inside = not inside
            previous_x, previous_y = current_x, current_y
        return inside
