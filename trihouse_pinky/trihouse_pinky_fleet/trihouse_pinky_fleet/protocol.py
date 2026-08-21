"""Control Tower 경계에서 ROS 없이 NDJSON 명령을 엄격히 해석하는 정책."""

from dataclasses import dataclass
import math
from typing import Any


class ProtocolError(ValueError):
    pass


def classify_gateway_response(payload: dict[str, Any]) -> str:
    """FMS TCP 응답이 실행 명령으로 재해석되는 ACK loop를 차단한다."""
    message_type = payload.get('type')
    if message_type == 'ack':
        return 'ack'
    if message_type == 'event_rejected':
        return 'event_rejected'
    return 'command'


@dataclass(frozen=True)
class TaskContextCommand:
    active: bool
    job_id: int
    job_step_id: int
    assignment_revision: int
    rmf_task_id: str
    command_id: str
    map_revision: str
    command_source: str


@dataclass(frozen=True)
class TransportCommand:
    message_id: str
    task_context: TaskContextCommand
    dropoff_location_id: str
    destination_code: str
    frame_id: str
    x: float
    y: float
    yaw: float
    mode: str
    requires_precise_stop: bool


@dataclass(frozen=True)
class EmergencyCommand:
    message_id: str
    kind: str
    operator_id: str = ''
    reason: str = ''


@dataclass(frozen=True)
class KeepOutZoneCommand:
    message_id: str
    zone_id: str
    points: tuple[tuple[float, float], ...]
    reason: str
    valid_for_s: float


@dataclass(frozen=True)
class ClearKeepOutZoneCommand:
    message_id: str
    zone_id: str
    operator_id: str


def parse_transport_command(payload: dict[str, Any]) -> TransportCommand:
    required = ('message_id', 'task_context', 'dropoff_location_id', 'destination_code', 'dropoff_pose')
    if payload.get('type') != 'execute_transport' or any(not payload.get(key) for key in required):
        raise ProtocolError('execute_transport has missing required fields')
    context = payload['task_context']
    context_required = (
        'job_id', 'job_step_id', 'assignment_revision', 'command_id',
        'map_revision', 'command_source',
    )
    if not isinstance(context, dict) or not context.get('active') or any(
        context.get(key) in (None, '') for key in context_required
    ):
        raise ProtocolError('execute_transport requires an active task_context')
    try:
        job_id = int(context['job_id'])
        job_step_id = int(context['job_step_id'])
        assignment_revision = int(context['assignment_revision'])
    except (TypeError, ValueError) as error:
        raise ProtocolError('task_context numeric identifiers are invalid') from error
    if job_id <= 0 or job_step_id <= 0 or assignment_revision <= 0:
        raise ProtocolError('task_context identifiers must be positive')
    pose = payload['dropoff_pose']
    if not isinstance(pose, dict) or any(key not in pose for key in ('frame_id', 'x', 'y', 'yaw')):
        raise ProtocolError('dropoff_pose requires frame_id, x, y, yaw')
    if pose['frame_id'] != 'map':
        raise ProtocolError('dropoff_pose frame_id must be map')
    mode = payload.get('mode', 'TRANSPORT')
    if mode not in ('TRANSPORT', 'RETURN_TO_WAIT', 'RETURN_TO_CHARGE'):
        raise ProtocolError('unsupported transport mode')
    try:
        return TransportCommand(
            str(payload['message_id']),
            TaskContextCommand(
                True, job_id, job_step_id, assignment_revision,
                str(context.get('rmf_task_id', '')),
                str(context['command_id']), str(context['map_revision']),
                str(context['command_source']),
            ),
            str(payload['dropoff_location_id']), str(payload['destination_code']), 'map', float(pose['x']), float(pose['y']), float(pose['yaw']), mode, bool(payload.get('requires_precise_stop', False)),
        )
    except (TypeError, ValueError) as error:
        raise ProtocolError('dropoff_pose coordinates must be numeric') from error


def parse_emergency_command(payload: dict[str, Any]) -> EmergencyCommand:
    kind = payload.get('type')
    message_id = payload.get('message_id')
    if kind not in ('emergency_request', 'clear_emergency') or not message_id:
        raise ProtocolError('emergency command requires type and message_id')
    operator_id = str(payload.get('operator_id', ''))
    if kind == 'clear_emergency' and not operator_id:
        raise ProtocolError('clear_emergency requires operator_id')
    return EmergencyCommand(str(message_id), str(kind), operator_id, str(payload.get('reason', '')))


def parse_keep_out_zone(payload: dict[str, Any]) -> KeepOutZoneCommand:
    if payload.get('type') != 'keep_out_zone' or not payload.get('message_id') or not payload.get('zone_id'):
        raise ProtocolError('keep_out_zone requires message_id and zone_id')
    raw_points = payload.get('points')
    if not isinstance(raw_points, list) or len(raw_points) < 3:
        raise ProtocolError('keep_out_zone requires at least three points')
    try:
        points = tuple((float(point[0]), float(point[1])) for point in raw_points)
    except (IndexError, TypeError, ValueError) as error:
        raise ProtocolError('keep_out_zone points must be numeric x/y pairs') from error
    valid_for_s = float(payload.get('valid_for_s', 0.0))
    if valid_for_s < 0:
        raise ProtocolError('valid_for_s cannot be negative')
    return KeepOutZoneCommand(str(payload['message_id']), str(payload['zone_id']), points, str(payload.get('reason', '')), valid_for_s)


def parse_clear_keep_out_zone(payload: dict[str, Any]) -> ClearKeepOutZoneCommand:
    if payload.get('type') != 'clear_keep_out_zone' or not payload.get('message_id') or not payload.get('zone_id') or not payload.get('operator_id'):
        raise ProtocolError('clear_keep_out_zone requires message_id, zone_id, operator_id')
    return ClearKeepOutZoneCommand(str(payload['message_id']), str(payload['zone_id']), str(payload['operator_id']))


# 사람 관측이 만료되기까지의 기본 수명. 보내는 쪽이 `ttl_ms` 를 빠뜨렸을 때 쓴다.
#
# 만료가 없으면 한 번 본 사람이 영원히 옆에 서 있는 것이 되어 로봇이 계속
# 감속한다. 추론이 10~15 Hz 로 도므로 그보다 몇 배 넉넉하되, 사람이 프레임을
# 벗어난 뒤에는 곧 풀려야 한다.
DEFAULT_PERSON_TTL_MS = 600


@dataclass(frozen=True)
class PersonObservation:
    """관제가 내려보낸 사람 관측. **명령이 아니다.**

    `message_id` 도 ack 도 없다 — 10~15 Hz 로 흐르는 것에 명령 규약을 씌우면
    중복 목록이 무한히 커지고 ack 가 역류해 링크를 채운다. 최신 값만 의미가 있고
    신선도는 `ttl_ms` 가 싣는다.

    `pose` 는 카메라 캘리브레이션이 끝나기 전까지 `None` 이다. 지어낸 좌표를
    싣지 않는다 — `config/cameras.yaml` 이 `map_pose` 를 `null` 로 두는 것과 같은
    이유다. (0, 0) 으로 채우면 거리 0, 즉 최대 위험으로 읽혀 안전해 보이지만,
    나중에 진짜 값이 들어와도 아무도 차이를 느끼지 못한다.
    """

    camera_id: str
    confidence: float
    ttl_ms: int
    observed_at_ms: int = 0
    track_id: str = ''
    model_version: str = ''
    pose_class: str = ''
    pose: tuple[float, float] | None = None
    bbox: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class MarkerObservationCommand:
    """4060이 FMS/TCP를 거쳐 내린 ArUco의 camera-frame 관측.

    ``translation_m``은 아직 base 좌표가 아니다. 카메라 장착 TF를 가진
    onboard vision transformer만 이 값을 base-frame으로 바꿀 수 있다.
    """

    camera_id: str
    marker_family: str
    marker_id: str
    translation_m: tuple[float, float, float]
    confidence: float
    ttl_ms: int
    observed_at_ms: int


def parse_marker_observation(payload: dict[str, Any]) -> MarkerObservationCommand:
    """marker docking에 쓸 수 있는 camera-frame 관측만 통과시킨다."""
    if payload.get('type') != 'marker_observation':
        raise ProtocolError('marker_observation requires type=marker_observation')
    camera_id = str(payload.get('camera_id', '')).strip()
    marker_id = str(payload.get('marker_id', '')).strip()
    if not camera_id or not marker_id:
        raise ProtocolError('marker_observation requires camera_id and marker_id')
    if payload.get('marker_family') != 'DICT_5X5_50':
        raise ProtocolError('marker_observation marker_family must be DICT_5X5_50')
    raw_translation = payload.get('translation_m')
    if not isinstance(raw_translation, dict) or any(
        name not in raw_translation for name in ('x', 'y', 'z')
    ):
        raise ProtocolError('marker_observation translation_m requires x, y, z')
    try:
        translation = tuple(float(raw_translation[name]) for name in ('x', 'y', 'z'))
        confidence = float(payload['confidence'])
        ttl_ms = int(payload['ttl_ms'])
        observed_at_ms = int(payload['observed_at_ms'])
    except (KeyError, TypeError, ValueError) as error:
        raise ProtocolError('marker_observation numeric fields are invalid') from error
    if not all(math.isfinite(value) for value in translation):
        raise ProtocolError('marker_observation translation_m must be finite')
    if not 0.0 < confidence <= 1.0:
        raise ProtocolError('marker_observation confidence must be within (0, 1]')
    if ttl_ms <= 0 or ttl_ms > 60_000 or observed_at_ms < 0:
        raise ProtocolError('marker_observation ttl_ms or observed_at_ms is invalid')
    return MarkerObservationCommand(
        camera_id=camera_id,
        marker_family='DICT_5X5_50',
        marker_id=marker_id,
        translation_m=translation,
        confidence=confidence,
        ttl_ms=ttl_ms,
        observed_at_ms=observed_at_ms,
    )


def _person_bbox(payload: dict[str, Any]) -> tuple[int, int, int, int] | None:
    raw = payload.get('bbox')
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ProtocolError('person_detection bbox must be a mapping')
    fields = ('x_offset', 'y_offset', 'width', 'height')
    missing = [name for name in fields if name not in raw]
    if missing:
        # 반쪽 사각형은 쓸 데가 없다. 조용히 0 으로 메우면 화면 왼쪽 위에 붙은
        # 상자가 되어 나중에 오검출을 되짚을 때 사람을 엉뚱한 곳에서 찾는다.
        raise ProtocolError(f"person_detection bbox is missing {missing[0]}")
    try:
        values = tuple(int(raw[name]) for name in fields)
    except (TypeError, ValueError) as error:
        raise ProtocolError('person_detection bbox must be integers') from error
    if any(value < 0 for value in values):
        raise ProtocolError('person_detection bbox cannot be negative')
    return values


def _person_pose(payload: dict[str, Any]) -> tuple[float, float] | None:
    raw = payload.get('pose')
    if raw is None:
        return None
    if not isinstance(raw, dict) or 'x' not in raw or 'y' not in raw:
        raise ProtocolError('person_detection pose requires x and y')
    try:
        return float(raw['x']), float(raw['y'])
    except (TypeError, ValueError) as error:
        raise ProtocolError('person_detection pose must be numeric') from error


def parse_person_detection(payload: dict[str, Any]) -> PersonObservation:
    """5080 추론이 4060 관제를 거쳐 내려온 사람 관측을 해석한다.

    `VLM/RL → Safety Supervisor 우회` 가 금지 연결이므로 이 경로만 쓴다
    (`docs/architecture/system_overview.md`).
    """
    if payload.get('type') != 'person_detection':
        raise ProtocolError('person_detection requires type=person_detection')
    camera_id = str(payload.get('camera_id', '')).strip()
    if not camera_id:
        # 어느 카메라가 봤는지 모르면 오검출을 되짚을 수 없다. 배경 물체를
        # 사람으로 잡는 사례가 실제로 있었다(벽에 달린 금속 체인).
        raise ProtocolError('person_detection requires camera_id')
    if 'confidence' not in payload:
        raise ProtocolError('person_detection requires confidence')
    try:
        confidence = float(payload['confidence'])
    except (TypeError, ValueError) as error:
        raise ProtocolError('person_detection confidence must be numeric') from error
    if not 0.0 < confidence <= 1.0:
        # 안전 gate 는 `confidence > 0` 을 사람 있음으로 읽는다. 0 은 "사람 없음"
        # 을 뜻하려는 의도겠지만 gate 에서 조용히 무시되어 보내지 않은 것과
        # 구분되지 않는다. 사람이 없으면 보내지 않는 것이 계약이다.
        raise ProtocolError('person_detection confidence must be within (0, 1]')
    ttl_ms = int(payload.get('ttl_ms', DEFAULT_PERSON_TTL_MS))
    if ttl_ms < 0:
        raise ProtocolError('person_detection ttl_ms cannot be negative')
    return PersonObservation(
        camera_id=camera_id,
        confidence=confidence,
        ttl_ms=ttl_ms or DEFAULT_PERSON_TTL_MS,
        observed_at_ms=int(payload.get('observed_at_ms', 0)),
        track_id=str(payload.get('track_id', '')),
        model_version=str(payload.get('model_version', '')),
        pose_class=str(payload.get('pose_class', '')),
        pose=_person_pose(payload),
        bbox=_person_bbox(payload),
    )
