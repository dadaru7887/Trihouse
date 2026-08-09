"""Control Tower↔OMX NDJSON payload를 엄격히 검증하는 경계."""
from __future__ import annotations

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
