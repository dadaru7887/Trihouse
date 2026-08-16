"""Control Tower↔OMX NDJSON payload를 엄격히 검증하는 경계."""

from dataclasses import dataclass
from typing import Any


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class OmxCommand:
    message_id: str
    kind: str
    job_id: str
    job_step_id: str
    order_id: str
    item_id: str
    shelf_id: str
    slot_id: str


@dataclass(frozen=True)
class OmxResult:
    message_id: str
    command_id: str
    job_id: str
    job_step_id: str
    success: bool


def parse_omx_command(payload: dict[str, Any]) -> OmxCommand:
    required = ('message_id', 'job_id', 'job_step_id', 'order_id', 'item_id', 'shelf_id', 'slot_id')
    if payload.get('type') not in ('omx_pick', 'omx_place_shelf', 'omx_load_pinky') or any(not payload.get(field) for field in required):
        raise ProtocolError('OMX command has missing required fields')
    return OmxCommand(*(str(payload[field]) for field in ('message_id', 'type', 'job_id', 'job_step_id', 'order_id', 'item_id', 'shelf_id', 'slot_id')))


def parse_omx_result(payload: dict[str, Any]) -> OmxResult:
    required = ('message_id', 'command_id', 'job_id', 'job_step_id')
    if payload.get('type') != 'omx_result' or any(not payload.get(field) for field in required) or not isinstance(payload.get('success'), bool):
        raise ProtocolError('OMX result has missing required fields')
    return OmxResult(str(payload['message_id']), str(payload['command_id']), str(payload['job_id']), str(payload['job_step_id']), payload['success'])


class OmxMessageGate:
    def __init__(self) -> None:
        self._commands: dict[str, OmxCommand] = {}
        self._seen_result_ids: set[str] = set()

    def register_command(self, command: OmxCommand) -> bool:
        if command.message_id in self._commands:
            return False
        self._commands[command.message_id] = command
        return True

    def accept_result(self, result: OmxResult) -> bool:
        if result.message_id in self._seen_result_ids:
            return False
        command = self._commands.get(result.command_id)
        if command is None or (command.job_id, command.job_step_id) != (result.job_id, result.job_step_id):
            return False
        self._seen_result_ids.add(result.message_id)
        return True


@dataclass(frozen=True)
class OmxAssignedCommand:
    """P0 시뮬레이터가 받는 배정 고정 명령.

    `command_uuid`, `job_step_id`, `assignment_revision`, `omx_id`, 기대 품목,
    마커 ID가 모두 있어야 한다. 하나라도 빠지면 어떤 상태도 바뀌지 않는다.
    """

    command_uuid: str
    kind: str
    job_step_id: int
    assignment_revision: int
    omx_id: str
    expected_items: tuple[str, ...]
    marker_id: int

    def as_payload(self) -> dict[str, Any]:
        return {
            'command_uuid': self.command_uuid,
            'kind': self.kind,
            'job_step_id': self.job_step_id,
            'assignment_revision': self.assignment_revision,
            'omx_id': self.omx_id,
            'expected_items': list(self.expected_items),
            'marker_id': self.marker_id,
        }


ASSIGNED_COMMAND_KINDS = ('prepare', 'load', 'hold', 'reset')


def parse_omx_assigned_command(payload: dict[str, Any]) -> OmxAssignedCommand:
    """배정 고정 OMX 명령을 엄격히 검증한다."""
    required = (
        'command_uuid', 'kind', 'job_step_id', 'assignment_revision',
        'omx_id', 'expected_items', 'marker_id',
    )
    missing = [field for field in required if field not in payload]
    if missing:
        raise ProtocolError(
            f"OMX assigned command is missing {', '.join(sorted(missing))}"
        )
    kind = str(payload['kind']).strip()
    if kind not in ASSIGNED_COMMAND_KINDS:
        raise ProtocolError(f'unsupported OMX command kind: {kind}')
    command_uuid = str(payload['command_uuid']).strip()
    omx_id = str(payload['omx_id']).strip()
    if not command_uuid or not omx_id:
        raise ProtocolError('command_uuid and omx_id are required')
    job_step_id = _positive_int(payload['job_step_id'], 'job_step_id')
    revision = _positive_int(payload['assignment_revision'], 'assignment_revision')
    raw_items = payload['expected_items']
    if isinstance(raw_items, (str, bytes)) or not isinstance(raw_items, (list, tuple)):
        raise ProtocolError('expected_items must be a list')
    items = tuple(str(item).strip() for item in raw_items)
    if not items or any(not item for item in items):
        raise ProtocolError('expected_items must name at least one item')
    marker_id = payload['marker_id']
    if isinstance(marker_id, bool) or not isinstance(marker_id, int) or marker_id < 0:
        raise ProtocolError('marker_id must be a non-negative marker identifier')
    return OmxAssignedCommand(
        command_uuid=command_uuid,
        kind=kind,
        job_step_id=job_step_id,
        assignment_revision=revision,
        omx_id=omx_id,
        expected_items=items,
        marker_id=marker_id,
    )


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProtocolError(f'{field} must be a positive integer')
    return value
