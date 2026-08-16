"""비상 구역과 해제 후 복귀를 FMS 권한으로 결정하는 정책.

RMF는 임시 구역을 받고, 즉시 물리 정지는 Pinky Safety Supervisor가 독립 수행한다.
"""

from dataclasses import dataclass, replace


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


# --- P0 비상 fixture와 운영자 결정 -------------------------------------------
#
# Fixture 1은 이동 중 Pinky 전도, Fixture 2는 창고 내 전도다. 둘 다 즉시
# 해당 작업을 보류한다. `비상경보 발령`은 사건을 확정하고 보류를 유지하며,
# `작업 계속 진행`은 작업자와 사유를 남기고 보류를 풀어 같은 Job의 Nav2
# 경로를 다시 계산하고 RMF 일정을 다시 등록한다. 대화상자를 그냥 닫으면
# 아무 일도 일어나지 않는다.

from control_tower.gateway.operations_feed import select_event_cameras


EMERGENCY_DECISIONS = ('RAISE_ALARM', 'CONTINUE_WORK')
EMERGENCY_FIXTURES = ('PINKY_FALL', 'WAREHOUSE_FALL')


@dataclass(frozen=True)
class EmergencyDecision:
    worker_id: str
    decision: str
    reason: str


@dataclass(frozen=True)
class EmergencyIncident:
    incident_id: str
    kind: str
    job_id: str
    camera_ids: tuple[str, ...]
    held: bool


@dataclass(frozen=True)
class EmergencyOutcome:
    incident_id: str
    confirmed: bool
    hold_released: bool
    worker_id: str = ''
    reason: str = ''
    resumed_job_id: str = ''
    recompute_nav2_path: bool = False
    reregister_rmf_itinerary: bool = False


def _extend_emergency_workflow() -> None:
    """`EmergencyWorkflow`에 P0 fixture 동작을 붙인다."""

    def _fixtures(self) -> dict:
        store = getattr(self, '_fixture_incidents', None)
        if store is None:
            store = {}
            self._fixture_incidents = store
        return store

    def _outcomes(self) -> dict:
        store = getattr(self, '_fixture_outcomes', None)
        if store is None:
            store = {}
            self._fixture_outcomes = store
        return store

    def open_fixture(
        self,
        incident_id: str,
        *,
        kind: str,
        job_id: str,
        robot_id: str = '',
        location_id: str = '',
    ) -> EmergencyIncident:
        if kind not in EMERGENCY_FIXTURES:
            raise ValueError(f'unsupported emergency fixture: {kind}')
        if not incident_id.strip() or not job_id.strip():
            raise ValueError('incident_id and job_id are required')
        selection = select_event_cameras(
            kind=kind, robot_id=robot_id, location_id=location_id
        )
        incident = EmergencyIncident(
            incident_id=incident_id,
            kind=kind,
            job_id=job_id,
            camera_ids=selection.camera_ids,
            # 두 fixture 모두 영향을 받은 작업을 즉시 보류한다.
            held=True,
        )
        _fixtures(self)[incident_id] = incident
        return incident

    def is_held(self, job_id: str) -> bool:
        return any(
            incident.job_id == job_id and incident.held
            for incident in _fixtures(self).values()
        )

    def decide(self, incident_id: str, decision: EmergencyDecision) -> EmergencyOutcome:
        recorded = _outcomes(self).get(incident_id)
        if recorded is not None:
            # 첫 결정만 유효하다. 이후 요청은 기록된 결과를 그대로 돌려준다.
            return recorded
        incident = _fixtures(self).get(incident_id)
        if incident is None:
            raise ValueError(f'unknown emergency incident {incident_id}')
        if not decision.worker_id.strip():
            raise ValueError('worker_id is required to decide an emergency')
        if decision.decision not in EMERGENCY_DECISIONS:
            raise ValueError(f'unsupported emergency decision: {decision.decision}')

        if decision.decision == 'RAISE_ALARM':
            outcome = EmergencyOutcome(
                incident_id=incident_id,
                confirmed=True,
                hold_released=False,
                worker_id=decision.worker_id,
                reason=decision.reason,
            )
        else:
            _fixtures(self)[incident_id] = replace(incident, held=False)
            outcome = EmergencyOutcome(
                incident_id=incident_id,
                confirmed=False,
                hold_released=True,
                worker_id=decision.worker_id,
                reason=decision.reason,
                resumed_job_id=incident.job_id,
                recompute_nav2_path=True,
                reregister_rmf_itinerary=True,
            )
        _outcomes(self)[incident_id] = outcome
        return outcome

    def dismiss(self, incident_id: str) -> EmergencyOutcome:
        """대화상자를 닫는다. 상태도 감사 기록도 바뀌지 않는다."""
        if incident_id not in _fixtures(self):
            raise ValueError(f'unknown emergency incident {incident_id}')
        return EmergencyOutcome(
            incident_id=incident_id, confirmed=False, hold_released=False
        )

    def decisions(self, incident_id: str) -> tuple[EmergencyOutcome, ...]:
        recorded = _outcomes(self).get(incident_id)
        return () if recorded is None else (recorded,)

    EmergencyWorkflow.open_fixture = open_fixture
    EmergencyWorkflow.is_held = is_held
    EmergencyWorkflow.decide = decide
    EmergencyWorkflow.dismiss = dismiss
    EmergencyWorkflow.decisions = decisions


_extend_emergency_workflow()
