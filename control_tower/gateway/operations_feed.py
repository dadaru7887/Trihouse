"""Gateway만 노출하는 메모리 기반 운영 read model.

HTTP/WebSocket adapter가 immutable view를 직렬화한다. UI는 DB·RMF·ROS를 직접 호출하지 않는다.

지도 화면의 1차 정보는 Nav2가 실제로 계산한 경로와 로봇이 지나온 궤적이다.
내부 bootstrap graph는 운영자 레이어가 아니므로 노출하지 않는다. Nav2 경로와
RMF 일정이 허용 오차를 넘게 어긋나면 `PATH_SCHEDULE_MISMATCH`를 내고 로봇을
보류 상태로 둔다.
"""

import math
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
class CameraFixture:
    """P0가 등록만 하는 카메라. 여섯 대를 물리적으로 연결하지 않는다."""

    camera_id: str
    role: str
    attached_to: str | None
    mediamtx_path: str
    # P1 캘리브레이션 전까지 좌표를 지어내지 않는다.
    map_pose: tuple[float, float, float] | None = None


CAMERA_FIXTURES = (
    CameraFixture('CAM-PK-01', 'pinky_travel', 'PK_01', 'fixtures/pinky_01_travel'),
    CameraFixture('CAM-PK-02', 'pinky_travel', 'PK_02', 'fixtures/pinky_02_travel'),
    CameraFixture('CAM-OMX-01-WRIST', 'omx_wrist', 'OMX_01', 'fixtures/omx_01_wrist'),
    CameraFixture('CAM-OMX-02-WRIST', 'omx_wrist', 'OMX_02', 'fixtures/omx_02_wrist'),
    CameraFixture('CAM-FIXED-01', 'warehouse_fixed', None, 'fixtures/warehouse_fixed_01'),
    CameraFixture('CAM-FIXED-02', 'warehouse_fixed', None, 'fixtures/warehouse_fixed_02'),
)

_PINKY_CAMERA = {'PK_01': 'CAM-PK-01', 'PK_02': 'CAM-PK-02'}
_OMX_WRIST_CAMERA = {'OMX_01': 'CAM-OMX-01-WRIST', 'OMX_02': 'CAM-OMX-02-WRIST'}
# 상온/냉장 구역은 고정 카메라 1번, 냉동/포장 구역은 2번이 비춘다.
_FIXED_CAMERA_BY_AREA = {
    'WH-AMB-01': 'CAM-FIXED-01',
    'WH-CHL-01': 'CAM-FIXED-01',
    'WH-FRZ-01': 'CAM-FIXED-02',
    'PACKING-01': 'CAM-FIXED-02',
}


@dataclass(frozen=True)
class CameraSelection:
    camera_ids: tuple[str, ...]
    auto_close_on_success: bool


def select_event_cameras(
    *,
    kind: str,
    robot_id: str = '',
    omx_id: str = '',
    location_id: str = '',
) -> CameraSelection:
    """사건 원인이 어떤 카메라를 여는지 결정한다.

    Pinky 영상은 이동 감시용이며 절대 OMX 적재 증거로 선택되지 않는다.
    """
    if kind in ('PINKY_FALL', 'MANUAL_TRAVEL_VIEW'):
        if not robot_id:
            raise ValueError('robot_id is required to select a Pinky camera')
        camera = _PINKY_CAMERA.get(robot_id)
        return CameraSelection(
            (camera,) if camera else (),
            auto_close_on_success=kind == 'MANUAL_TRAVEL_VIEW',
        )
    if kind == 'WAREHOUSE_FALL':
        if not location_id:
            raise ValueError('location_id is required to select a fixed camera')
        camera = _fixed_camera(location_id)
        return CameraSelection((camera,) if camera else (), auto_close_on_success=False)
    if kind in ('OMX_QR', 'OMX_PICK', 'OMX_LOAD'):
        if not omx_id:
            raise ValueError('omx_id is required to select an OMX wrist camera')
        cameras = [_OMX_WRIST_CAMERA.get(omx_id)]
        if location_id:
            cameras.append(_fixed_camera(location_id))
        return CameraSelection(
            tuple(camera for camera in cameras if camera),
            auto_close_on_success=True,
        )
    return CameraSelection((), auto_close_on_success=True)


def _fixed_camera(location_id: str) -> str | None:
    for area, camera in _FIXED_CAMERA_BY_AREA.items():
        if location_id == area or location_id.startswith(f'{area}-'):
            return camera
    return None


@dataclass(frozen=True)
class PathProjection:
    """지도 화면이 그리는 실제 경로 정보."""

    robot_id: str
    map_revision: str
    nav2_global_path: tuple[tuple[float, float], ...]
    nav2_local_path: tuple[tuple[float, float], ...]
    actual_trail: tuple[tuple[float, float], ...]
    # RMF timed trajectory는 진단 토글에서만 보이는 선택 정보다.
    rmf_timed_trajectory: tuple[tuple[float, float, float], ...]
    goal_pose: tuple[float, float, float]


@dataclass(frozen=True)
class OperationsSnapshot:
    robots: tuple[RobotView, ...]
    jobs: tuple[JobView, ...]
    incidents: tuple[IncidentView, ...]
    paths: tuple[PathProjection, ...] = ()
    cameras: tuple[CameraFixture, ...] = CAMERA_FIXTURES
    # 내부 bootstrap graph는 운영자 레이어가 아니다.
    bootstrap_graph_visible: bool = False


class OperationsFeed:
    def __init__(self, *, path_tolerance_m: float = 0.5) -> None:
        if path_tolerance_m <= 0:
            raise ValueError('path tolerance must be positive')
        self._path_tolerance_m = path_tolerance_m
        self._robots: dict[str, RobotView] = {}
        self._jobs: dict[str, JobView] = {}
        self._incidents: dict[str, IncidentView] = {}
        self._paths: dict[str, PathProjection] = {}
        self._held: set[str] = set()
        self._events: list[OperationsEvent] = []

    def upsert_path(self, projection: PathProjection) -> None:
        """Nav2 경로와 RMF 일정이 어긋나면 로봇을 보류한다."""
        self._paths[projection.robot_id] = projection
        self._events.append(
            OperationsEvent('PATH_UPDATED', projection.robot_id, 1)
        )
        if _paths_disagree(projection, self._path_tolerance_m):
            self._held.add(projection.robot_id)
            self._events.append(
                OperationsEvent('PATH_SCHEDULE_MISMATCH', projection.robot_id, 90)
            )
        else:
            self._held.discard(projection.robot_id)

    def is_held(self, robot_id: str) -> bool:
        return robot_id in self._held

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
            tuple(sorted(self._paths.values(), key=lambda path: path.robot_id)),
        )

    def drain_events(self) -> tuple[OperationsEvent, ...]:
        events = tuple(sorted(self._events, key=lambda event: -event.priority))
        self._events.clear()
        return events


def _paths_disagree(projection: PathProjection, tolerance_m: float) -> bool:
    """Nav2 경로와 RMF 일정의 종점 차이가 허용 오차를 넘는지 본다."""
    if not projection.nav2_global_path or not projection.rmf_timed_trajectory:
        return False
    nav_x, nav_y = projection.nav2_global_path[-1]
    _t, rmf_x, rmf_y = projection.rmf_timed_trajectory[-1]
    return math.hypot(nav_x - rmf_x, nav_y - rmf_y) > tolerance_m


__all__ = [
    'CAMERA_FIXTURES',
    'CameraFixture',
    'CameraSelection',
    'IncidentView',
    'JobView',
    'OperationsEvent',
    'OperationsFeed',
    'OperationsSnapshot',
    'PathProjection',
    'RobotView',
    'select_event_cameras',
]
