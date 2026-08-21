"""Bounded NDJSON contract between the ROS 2 bridge and LeRobot worker."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


MAX_FRAME_BYTES = 1_048_576


class IpcProtocolError(ValueError):
    pass


def encode_message(message: dict[str, Any]) -> bytes:
    if not isinstance(message, dict):
        raise IpcProtocolError("MESSAGE_NOT_OBJECT")
    encoded = json.dumps(
        message, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8") + b"\n"
    if len(encoded) > MAX_FRAME_BYTES:
        raise IpcProtocolError("FRAME_TOO_LARGE")
    return encoded


def decode_message(frame: bytes) -> dict[str, Any]:
    if not frame.endswith(b"\n") or len(frame) > MAX_FRAME_BYTES:
        raise IpcProtocolError("INVALID_FRAME")
    try:
        message = json.loads(frame[:-1])
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IpcProtocolError("INVALID_JSON") from error
    if not isinstance(message, dict):
        raise IpcProtocolError("MESSAGE_NOT_OBJECT")
    return message


def validate_worker_command(
    command: dict[str, Any], *, local_device_id: str
) -> dict[str, Any]:
    required = {
        "schema_version",
        "command_uuid",
        "kind",
        "job_id",
        "job_step_id",
        "assignment_revision",
        "omx_id",
        "temperature_zone",
        "items",
    }
    if not required.issubset(command):
        raise IpcProtocolError("INCOMPLETE_COMMAND")
    if command["schema_version"] != 1:
        raise IpcProtocolError("UNSUPPORTED_SCHEMA")
    if command["omx_id"] != local_device_id:
        raise IpcProtocolError("DEVICE_MISMATCH")
    if command["kind"] not in {"prepare", "load", "hold", "reset"}:
        raise IpcProtocolError("UNSUPPORTED_KIND")
    if not isinstance(command["items"], list):
        raise IpcProtocolError("INVALID_ITEMS")
    return deepcopy(command)


def _fingerprint(command: dict[str, Any]) -> str:
    return hashlib.sha256(encode_message(command)).hexdigest()


@dataclass
class ResultCache:
    _results: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)

    def lookup(self, command: dict[str, Any]) -> dict[str, Any] | None:
        command_uuid = str(command.get("command_uuid", ""))
        cached = self._results.get(command_uuid)
        if cached is None:
            return None
        if cached[0] != _fingerprint(command):
            raise IpcProtocolError("COMMAND_UUID_CONFLICT")
        return deepcopy(cached[1])

    def store(self, command: dict[str, Any], result: dict[str, Any]) -> None:
        command_uuid = str(command.get("command_uuid", ""))
        if not command_uuid:
            raise IpcProtocolError("MISSING_COMMAND_UUID")
        existing = self.lookup(command)
        if existing is not None:
            if existing != result:
                raise IpcProtocolError("RESULT_CONFLICT")
            return
        self._results[command_uuid] = (_fingerprint(command), deepcopy(result))


__all__ = [
    "IpcProtocolError",
    "MAX_FRAME_BYTES",
    "ResultCache",
    "decode_message",
    "encode_message",
    "validate_worker_command",
]
