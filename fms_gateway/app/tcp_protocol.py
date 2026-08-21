"""로봇 NDJSON 메시지의 검증·세션 처리와 asyncio TCP 수신 경계."""

import asyncio
from dataclasses import dataclass
import inspect
import json
import logging
import math
from typing import Any, Collection, Iterable, Mapping
from uuid import UUID


SCHEMA_VERSION = 3

logger = logging.getLogger(__name__)


class ProtocolRejected(ValueError):
    """`event_rejected` 응답으로 노출할 안정적인 프로토콜 거절 사유."""


@dataclass(frozen=True)
class ProcessedMessage:
    """세션/스키마 검증을 통과해 Repository에 전달 가능한 메시지."""
    action: str
    robot_id: str
    payload: dict[str, Any]


def _reject(reason: str) -> None:
    """모든 검증 실패가 동일한 응답 경로를 타도록 예외로 중단한다."""
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


class PersonDetectionRoutingError(ValueError):
    """관측을 어느 로봇에 줘야 할지 정할 수 없다."""


def route_person_detection(camera_id: str, cameras: Iterable[Any]) -> str:
    """카메라 명부로 수신 로봇을 정한다. 요청이 `robot_id` 를 싣지 않는 이유다.

    `config/cameras.yaml` 의 `attached_to` 가 이미 답이고, 요청에 로봇을 함께
    실으면 둘이 어긋날 수 있다. 그 어긋남은 "엉뚱한 로봇이 감속한다" 로 나타나
    원인에서 아주 멀다.

    고정 카메라는 아직 라우팅할 수 없다 — 사람과 로봇의 위치를 둘 다 알아야
    하는데 캘리브레이션이 없다. 아무 로봇에나 보내는 대신 거절한다.
    """
    for camera in cameras:
        if camera.camera_id != camera_id:
            continue
        if not camera.attached_to:
            raise PersonDetectionRoutingError(
                f"{camera_id} is not attached to a robot; fixed cameras need calibration"
            )
        return camera.attached_to
    raise PersonDetectionRoutingError(f"unknown camera: {camera_id}")


class RobotLinkRegistry:
    """robot_id 로 살아 있는 연결을 찾아 서버가 먼저 말을 걸 수 있게 한다.

    기존 TCP 서버는 로봇이 보낸 줄에 **응답만** 했다. 사람 관측처럼 관제가 먼저
    내려보내야 하는 것에는 쓸 경로가 없었다.

    `push` 는 실패를 예외로 올리지 않고 사실로 돌려준다. 관측은 사람이 보이는
    동안 계속 흐르므로, 한 번 못 보낸 것이 보내는 쪽 루프를 멈추면 안 된다.
    """

    def __init__(self) -> None:
        self._links: dict[str, Any] = {}

    def attach(self, robot_id: str, writer: Any) -> None:
        """연결을 등록한다. 같은 로봇이 다시 붙으면 옛 연결을 대체한다.

        옛 소켓을 남겨 두면 관측이 아무도 듣지 않는 곳으로 사라지고, 로봇은
        사람이 보이는데도 감속하지 않는다.
        """
        self._links[robot_id] = writer

    def detach(self, robot_id: str, writer: Any) -> None:
        """그 연결이 아직 현재 연결일 때만 뗀다.

        끊긴 옛 연결이 뒤늦게 정리될 때 이미 붙은 새 연결까지 떼면, 재접속한
        로봇이 조용히 관측을 못 받는다.
        """
        if self._links.get(robot_id) is writer:
            del self._links[robot_id]

    def is_connected(self, robot_id: str) -> bool:
        return robot_id in self._links

    async def push(self, robot_id: str, payload: Mapping[str, Any]) -> bool:
        """한 줄을 밀어 넣는다. 보냈으면 True, 연결이 없거나 끊겼으면 False."""
        writer = self._links.get(robot_id)
        if writer is None:
            return False
        line = (json.dumps(dict(payload), separators=(",", ":")) + "\n").encode("utf-8")
        try:
            writer.write(line)
            await writer.drain()
        except (OSError, ConnectionError):
            # 끊긴 연결에 계속 쓰려 하면 관측마다 같은 예외가 난다. 여기서 뗀다.
            self.detach(robot_id, writer)
            return False
        return True


class ProtocolSession:
    """첫 hello의 robot/session identity에 영구적으로 묶인 연결 검증기."""

    def __init__(self, registered_robot_ids: Collection[str]):
        self._registered = frozenset(registered_robot_ids)
        self._robot_id: str | None = None
        self._session_id: str | None = None
        self._last_sequence = 0

    @property
    def robot_id(self) -> str | None:
        """hello로 묶인 로봇. 거절 로그가 어느 연결인지 가리키게 한다."""
        return self._robot_id

    def process(self, message: Mapping[str, Any]) -> ProcessedMessage:
        """연결 상태에 따라 hello를 강제하고 이후 메시지를 종류별 검증한다."""
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
        """telemetry 필드, 유한 수치, 실행 문맥, 단조 증가 sequence를 확인한다."""
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
        # 같은 연결의 과거/중복 상태가 최신 DB projection을 덮지 못하게 한다.
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
        """허용된 상태 전이 이벤트와 활성 task_context를 검증한다."""
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
    """연결별 세션과 줄 크기 제한을 둔 asyncio NDJSON 서버."""

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
        # 관제가 로봇에게 먼저 말을 걸어야 하는 것(사람 관측)을 위한 연결 장부.
        # 기존 서버는 로봇이 보낸 줄에 응답만 했다.
        self.links = RobotLinkRegistry()

    @property
    def port(self) -> int:
        if self._server is None or not self._server.sockets:
            return self._requested_port
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        """중복 시작을 허용하면서 설정된 주소에 TCP 서버를 연다."""
        if self._server is not None:
            return
        self._server = await asyncio.start_server(
            self._handle_connection,
            self.host,
            self._requested_port,
            limit=self._max_line_bytes + 1,
        )

    async def stop(self) -> None:
        """새 연결 수락을 닫고 기존 서버 소켓 종료를 기다린다."""
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """줄 단위 메시지를 처리하고 각 메시지에 ACK 또는 거절을 반환한다."""
        registered = self._registered_robot_ids()
        if inspect.isawaitable(registered):
            registered = await registered
        session = ProtocolSession(registered)
        peer = writer.get_extra_info("peername")
        attached: str | None = None
        try:
            # StreamReader limit과 명시적 길이 검사로 메모리 사용을 제한한다.
            while True:
                try:
                    line = await reader.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    await self._reject_line(writer, "LINE_TOO_LARGE", None, session, peer)
                    break
                if not line:
                    break
                if len(line) > self._max_line_bytes:
                    await self._reject_line(writer, "LINE_TOO_LARGE", None, session, peer)
                    break
                message: object = None
                try:
                    message = json.loads(line.decode("utf-8"))
                    if not isinstance(message, dict):
                        _reject("SCHEMA_INVALID")
                    processed = session.process(message)
                    # callback이 sync/async 어느 형태든 같은 프로토콜 경계를 지원한다.
                    callback_result = self._on_message(processed)
                    if inspect.isawaitable(callback_result):
                        await callback_result
                    response = {"type": "ack", "action": processed.action}
                    if processed.action == "robot_status":
                        response["sequence"] = processed.payload["sequence"]
                    elif processed.action == "task_event":
                        response["event_id"] = processed.payload["event_id"]
                    await self._write(writer, response)
                    # hello 를 통과한 뒤에야 robot_id 를 안다. 그때 장부에 올려야
                    # 관제가 이 연결로 관측을 밀어 넣을 수 있다.
                    if attached is None and session.robot_id:
                        attached = session.robot_id
                        self.links.attach(attached, writer)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    await self._reject_line(writer, "SCHEMA_INVALID", None, session, peer)
                except ProtocolRejected as error:
                    await self._reject_line(writer, str(error), message, session, peer)
        finally:
            if attached is not None:
                # 떼지 않으면 끊긴 소켓으로 계속 밀어 관측이 조용히 사라진다.
                self.links.detach(attached, writer)
            writer.close()
            await writer.wait_closed()

    async def _reject_line(
        self,
        writer: asyncio.StreamWriter,
        reason_code: str,
        message: object,
        session: "ProtocolSession",
        peer: object,
    ) -> None:
        """거절 사유와 함께 **어떤 메시지가** 거절됐는지를 응답과 로그 양쪽에 남긴다.

        거절 사유만으로는 원인을 찾을 수 없다. 로봇 쪽은 모든 거절을 같은 한 문장으로
        적고(`gateway_node.py` 의 `_drain`) Gateway 는 지금까지 아무것도 남기지 않아서,
        `MESSAGE_TYPE_UNSUPPORTED` 가 수십 건 쌓여도 어떤 메시지가 걸렸는지 알 수
        없었다. `message_type` 은 그 물음에 답하기 위한 것이며, 로봇도 이것을 받아
        자기 로그에 적는다.
        """
        response: dict[str, object] = {"type": "event_rejected", "reason_code": reason_code}
        message_type: object = None
        if isinstance(message, dict):
            message_type = message.get("type")
            if isinstance(message_type, str):
                response["message_type"] = message_type
            if isinstance(message.get("event_id"), str):
                response["event_id"] = message["event_id"]
        logger.warning(
            "robot message rejected: reason=%s type=%r robot=%r peer=%r",
            reason_code,
            message_type,
            session.robot_id,
            peer,
        )
        await self._write(writer, response)

    @staticmethod
    async def _write(writer: asyncio.StreamWriter, response: dict[str, object]) -> None:
        """응답도 한 줄 JSON으로 직렬화하고 커널 버퍼 전송을 기다린다."""
        writer.write((json.dumps(response, separators=(",", ":")) + "\n").encode("utf-8"))
        await writer.drain()
