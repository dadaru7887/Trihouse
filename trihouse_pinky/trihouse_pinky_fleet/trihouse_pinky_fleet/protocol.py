"""Control Tower 경계에서 ROS 없이 NDJSON 명령을 엄격히 해석하는 정책."""

from dataclasses import dataclass
from typing import Any


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class TransportCommand:
    message_id: str
    job_id: str
    job_step_id: str
    map_revision: str
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
    required = ('message_id', 'job_id', 'job_step_id', 'map_revision', 'dropoff_location_id', 'destination_code', 'dropoff_pose')
    if payload.get('type') != 'execute_transport' or any(not payload.get(key) for key in required):
        raise ProtocolError('execute_transport has missing required fields')
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
            str(payload['message_id']), str(payload['job_id']), str(payload['job_step_id']), str(payload['map_revision']),
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
