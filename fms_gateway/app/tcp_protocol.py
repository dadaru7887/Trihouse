"""Validation, processing, and a small asyncio NDJSON ingestion boundary."""

import asyncio
from dataclasses import dataclass
import inspect
import json
import math
from typing import Any, Collection, Mapping
from uuid import UUID


SCHEMA_VERSION = 3


class ProtocolRejected(ValueError):
    """A stable protocol rejection suitable for an event_rejected response."""


@dataclass(frozen=True)
class ProcessedMessage:
    action: str
    robot_id: str
    payload: dict[str, Any]


def _reject(reason: str) -> None:
    raise ProtocolRejected(reason)


def _require_fields(message: Mapping[str, Any], fields: Collection[str]) -> None:
    if any(field not in message for field in fields):
        _reject("SCHEMA_INVALID")


def _uuid(value: object) -> str:
    if not isinstance(value, str):
        _reject("SCHEMA_INVALID")
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError):
        _reject("SCHEMA_INVALID")


class ProtocolSession:
    """Validate one connection, which is permanently bound by its hello."""

    def __init__(self, registered_robot_ids: Collection[str]):
        self._registered = frozenset(registered_robot_ids)
        self._robot_id: str | None = None
        self._session_id: str | None = None
        self._last_sequence = 0

    def process(self, message: Mapping[str, Any]) -> ProcessedMessage:
        message_type = message.get("type")
        if self._robot_id is None:
            if message_type != "hello":
                _reject("HELLO_REQUIRED")
            return self._hello(message)
        if message.get("robot_id") != self._robot_id:
            _reject("ROBOT_ID_MISMATCH")
        if message.get("session_id") != self._session_id:
            _reject("SESSION_ID_MISMATCH")
        if message_type == "robot_status":
            return self._status(message)
        if message_type == "task_event":
            return self._task_event(message)
        if message_type == "heartbeat":
            self._base(message)
            return ProcessedMessage("heartbeat", self._robot_id or "", dict(message))
        _reject("MESSAGE_TYPE_UNSUPPORTED")

    def _base(self, message: Mapping[str, Any]) -> None:
        if message.get("schema_version") != SCHEMA_VERSION:
            _reject("SCHEMA_VERSION_UNSUPPORTED")

    def _hello(self, message: Mapping[str, Any]) -> ProcessedMessage:
        self._base(message)
        _require_fields(message, ("robot_id", "session_id"))
        robot_id = message["robot_id"]
        if not isinstance(robot_id, str) or robot_id not in self._registered:
            _reject("ROBOT_NOT_REGISTERED")
        self._robot_id = robot_id
        self._session_id = _uuid(message["session_id"])
        return ProcessedMessage("hello_accepted", robot_id, dict(message))

    def _status(self, message: Mapping[str, Any]) -> ProcessedMessage:
        self._base(message)
        required = (
            "sequence",
            "sent_at_ns",
            "map_revision",
            "frame_id",
            "pose",
            "twist",
            "navigation_state",
            "task_progress",
            "task_context",
            "battery_percentage",
            "battery_condition",
            "battery_policy",
            "safety_state",
            "cargo_state",
            "telemetry_valid",
            "execution_ready",
            "dispatchable",
            "ready",
            "errors",
        )
        _require_fields(message, required)
        sequence = message["sequence"]
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
            _reject("SCHEMA_INVALID")
        if sequence <= self._last_sequence:
            _reject("STALE_SEQUENCE")
        pose = message["pose"]
        twist = message["twist"]
        context = message["task_context"]
        if not isinstance(pose, Mapping) or not isinstance(twist, Mapping):
            _reject("SCHEMA_INVALID")
        _require_fields(pose, ("x", "y", "yaw"))
        _require_fields(twist, ("linear_x_mps", "angular_z_rps"))
        for value in (
            pose["x"], pose["y"], pose["yaw"],
            twist["linear_x_mps"], twist["angular_z_rps"],
            message["battery_percentage"], message["task_progress"],
        ):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
            ):
                _reject("SCHEMA_INVALID")
        self._validate_context(context)
        if context["active"] and context["map_revision"] != message["map_revision"]:
            _reject("SCHEMA_INVALID")
        if not isinstance(message["battery_condition"], Mapping):
            _reject("SCHEMA_INVALID")
        if not isinstance(message["battery_policy"], Mapping):
            _reject("SCHEMA_INVALID")
        if not isinstance(message["errors"], list):
            _reject("SCHEMA_INVALID")
        self._last_sequence = sequence
        return ProcessedMessage("robot_status", self._robot_id or "", dict(message))

    def _task_event(self, message: Mapping[str, Any]) -> ProcessedMessage:
        self._base(message)
        _require_fields(
            message,
            ("event_id", "event_type", "reason_code", "method_code", "detail", "task_context"),
        )
        _uuid(message["event_id"])
        if message["event_type"] not in {"started", "arrived", "canceled", "failed"}:
            _reject("SCHEMA_INVALID")
        self._validate_context(message["task_context"])
        if message["task_context"]["active"] is not True:
            _reject("SCHEMA_INVALID")
        return ProcessedMessage("task_event", self._robot_id or "", dict(message))

    @staticmethod
    def _validate_context(context: object) -> None:
        if not isinstance(context, Mapping):
            _reject("SCHEMA_INVALID")
        _require_fields(
            context,
            (
                "active",
                "job_id",
                "job_step_id",
                "assignment_revision",
                "rmf_task_id",
                "command_id",
                "map_revision",
                "command_source",
            ),
        )
        if not isinstance(context["active"], bool):
            _reject("SCHEMA_INVALID")
        if context["active"]:
            for field in ("job_id", "job_step_id", "assignment_revision"):
                value = context[field]
                if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                    _reject("SCHEMA_INVALID")
            for field in ("rmf_task_id", "map_revision"):
                value = context[field]
                if not isinstance(value, str) or not value.strip():
                    _reject("SCHEMA_INVALID")
            if context["command_source"] != "rmf":
                _reject("SCHEMA_INVALID")
            _uuid(context["command_id"])


class TcpIngestionServer:
    """Bounded, line-oriented asyncio server with per-connection sessions."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8788,
        registered_robot_ids,
        on_message,
        max_line_bytes: int = 64 * 1024,
    ):
        self.host = host
        self._requested_port = port
        self._registered_robot_ids = registered_robot_ids
        self._on_message = on_message
        self._max_line_bytes = max_line_bytes
        self._server: asyncio.AbstractServer | None = None

    @property
    def port(self) -> int:
        if self._server is None or not self._server.sockets:
            return self._requested_port
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(
            self._handle_connection,
            self.host,
            self._requested_port,
            limit=self._max_line_bytes + 1,
        )

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        registered = self._registered_robot_ids()
        if inspect.isawaitable(registered):
            registered = await registered
        session = ProtocolSession(registered)
        try:
            while True:
                try:
                    line = await reader.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    await self._write(writer, {"type": "event_rejected", "reason_code": "LINE_TOO_LARGE"})
                    break
                if not line:
                    break
                if len(line) > self._max_line_bytes:
                    await self._write(writer, {"type": "event_rejected", "reason_code": "LINE_TOO_LARGE"})
                    break
                try:
                    message = json.loads(line.decode("utf-8"))
                    if not isinstance(message, dict):
                        _reject("SCHEMA_INVALID")
                    processed = session.process(message)
                    callback_result = self._on_message(processed)
                    if inspect.isawaitable(callback_result):
                        await callback_result
                    response = {"type": "ack", "action": processed.action}
                    if processed.action == "robot_status":
                        response["sequence"] = processed.payload["sequence"]
                    elif processed.action == "task_event":
                        response["event_id"] = processed.payload["event_id"]
                    await self._write(writer, response)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    await self._write(writer, {"type": "event_rejected", "reason_code": "SCHEMA_INVALID"})
                except ProtocolRejected as error:
                    response = {"type": "event_rejected", "reason_code": str(error)}
                    if isinstance(message, dict) and isinstance(message.get("event_id"), str):
                        response["event_id"] = message["event_id"]
                    await self._write(writer, response)
        finally:
            writer.close()
            await writer.wait_closed()

    @staticmethod
    async def _write(writer: asyncio.StreamWriter, response: dict[str, object]) -> None:
        writer.write((json.dumps(response, separators=(",", ":")) + "\n").encode("utf-8"))
        await writer.drain()
