"""Control Tower NDJSON 명령을 검증 후 ExecuteTransport action으로 바꾸는 경계."""

import math
import os
import re
from collections import deque
from time import monotonic
from uuid import uuid4

import rclpy
from geometry_msgs.msg import Point32, Quaternion
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.node import Node
from std_msgs.msg import Bool
from trihouse_interfaces.action import ExecuteTransport
from trihouse_interfaces.msg import ConnectionState, KeepOutZone, RobotStatus, TaskEvent
from trihouse_interfaces.srv import ClearEmergency

from .measurement_log import MeasurementLogWriter
from .ndjson_client import NdjsonClient
from .event_outbox import EventOutbox
from .protocol import (
    ProtocolError,
    TransportCommand,
    classify_gateway_response,
    parse_clear_keep_out_zone,
    parse_emergency_command,
    parse_keep_out_zone,
    parse_transport_command,
)


def build_robot_status_payload(
    message: RobotStatus,
    *,
    sent_at_ns: int,
    session_id: str = '',
    sequence: int = 0,
) -> dict[str, object]:
    """ROS RobotStatus를 Control Tower용 JSON 객체로 변환한다.

    반환값은 NDJSON 네트워크 전송과 로컬 측정 로그에 함께 사용한다. 이렇게
    하면 관제에 보낸 값과 실험 파일에 기록한 값이 서로 달라지는 것을 막는다.
    """
    # 배터리 원본 검증 결과는 BatteryPolicyState 안의 condition에 들어 있다.
    condition = message.battery_policy.condition
    context = message.task_context
    pose = message.pose.pose
    orientation = pose.orientation
    yaw = math.atan2(
        2.0 * (
            orientation.w * orientation.z
            + orientation.x * orientation.y
        ),
        1.0 - 2.0 * (
            orientation.y * orientation.y
            + orientation.z * orientation.z
        ),
    )
    twist = message.twist
    return {
        'type': 'robot_status',
        'schema_version': 3,
        'robot_id': message.robot_id,
        'sent_at_ns': sent_at_ns,
        'session_id': session_id,
        'sequence': sequence,
        'frame_id': message.frame_id,
        'map_revision': message.map_revision,
        'pose': {
            'x': pose.position.x,
            'y': pose.position.y,
            'yaw': yaw,
        },
        'twist': {
            'linear_x_mps': twist.linear.x,
            'angular_z_rps': twist.angular.z,
        },
        'navigation_state': message.navigation_state,
        'task_progress': message.task_progress,
        'task_context': {
            'active': context.active,
            'job_id': context.job_id,
            'job_step_id': context.job_step_id,
            'assignment_revision': context.assignment_revision,
            'rmf_task_id': context.rmf_task_id,
            'command_id': context.command_id,
            'map_revision': context.map_revision,
            'command_source': context.command_source,
        },
        'telemetry_valid': message.telemetry_valid,
        'execution_ready': message.execution_ready,
        'dispatchable': message.dispatchable,
        'ready': message.ready,
        'battery_percentage': message.battery_percentage,
        'battery_condition': {
            'percentage': condition.percentage,
            'present': condition.present,
            'power_supply_status': condition.power_supply_status,
            'measurement_valid': condition.measurement_valid,
            'has_valid_sample': condition.has_valid_sample,
            'telemetry_fresh': condition.telemetry_fresh,
        },
        'battery_policy': {
            'state': message.battery_policy.state,
            'ready': message.battery_policy.ready,
            'reason_code': message.battery_policy.reason_code,
            'detail': message.battery_policy.detail,
        },
        'safety_state': message.safety.state,
        'cargo_state': message.cargo.state,
        'errors': list(message.errors),
    }


def build_task_event_payload(
    message: TaskEvent, *, session_id: str,
) -> dict[str, object]:
    """ROS TaskEvent를 FMS Gateway의 schema v3 wire 계약으로 바꾼다."""
    event_names = {
        TaskEvent.EVENT_STARTED: 'started',
        TaskEvent.EVENT_ARRIVED: 'arrived',
        TaskEvent.EVENT_CANCELED: 'canceled',
        TaskEvent.EVENT_FAILED: 'failed',
    }
    context = message.task_context
    return {
        'type': 'task_event',
        'schema_version': 3,
        'event_id': message.event_id,
        'robot_id': message.robot_id,
        'session_id': session_id,
        'task_context': {
            'active': context.active,
            'job_id': context.job_id,
            'job_step_id': context.job_step_id,
            'assignment_revision': context.assignment_revision,
            'rmf_task_id': context.rmf_task_id,
            'command_id': context.command_id,
            'map_revision': context.map_revision,
            'command_source': context.command_source,
        },
        'event_type': event_names[message.event_type],
        'reason_code': message.reason_code,
        'method_code': message.method_code,
        'detail': message.detail,
    }


def _stream_robot_id(robot_id: str) -> str:
    """로봇 ID를 디렉터리 경로로 해석되지 않는 안전한 파일명 토큰으로 바꾼다."""
    # 영문자·숫자·밑줄·점·하이픈 이외의 문자를 모두 밑줄로 치환한다.
    # 이어서 맨 앞의 점을 제거해 숨김 파일이나 `..` 경로 형태를 방지한다.
    token = re.sub(r"[^A-Za-z0-9_.-]", "_", robot_id).lstrip(".")
    # 모든 문자가 제거되어 빈 값이 되면 예측 가능한 기본 이름을 사용한다.
    return token or "unknown"


def _context_identity(context: object) -> tuple[object, ...]:
    if not isinstance(context, dict):
        context = {
            name: getattr(context, name)
            for name in (
                'job_id', 'job_step_id', 'assignment_revision', 'rmf_task_id',
                'command_id', 'map_revision', 'command_source',
            )
        }
    return tuple(
        context[name]
        for name in (
            'job_id', 'job_step_id', 'assignment_revision', 'rmf_task_id',
            'command_id', 'map_revision', 'command_source',
        )
    )


def _event_required_navigation_state(event_type: str) -> int | None:
    return {
        'started': 1,
        'arrived': 2,
        'canceled': 3,
        'failed': 4,
    }.get(event_type)


def _with_replay_sequence(
    status_payload: dict[str, object], *, sequence: int, sent_at_ns: int,
) -> dict[str, object]:
    replay = dict(status_payload)
    replay['sequence'] = sequence
    replay['sent_at_ns'] = sent_at_ns
    return replay


def _status_evidence_is_current(
    status_payload: dict[str, object], *, runtime_id: str, now: float,
) -> bool:
    captured_at = status_payload.get('_captured_monotonic')
    return (
        status_payload.get('_runtime_id') == runtime_id
        and isinstance(captured_at, (int, float))
        and now - float(captured_at) <= 1.5
    )


class GatewayNode(Node):
    """Pinky의 ROS graph와 Control Tower의 NDJSON 연결을 중계하는 노드."""

    def __init__(self) -> None:
        """통신 파라미터, 측정 기록기, ROS 입출력과 네트워크 client를 준비한다."""
        super().__init__('fleet_gateway')

        # 로봇 식별자와 Control Tower TCP endpoint를 launch에서 바꿀 수 있게 한다.
        self.declare_parameter('robot_id', 'PK_01')
        self.declare_parameter('control_host', '127.0.0.1')
        self.declare_parameter('control_port', 8788)

        # POC 측정 로그의 활성화 여부, 저장 위치와 실험 run ID다.
        self.declare_parameter('measurement_logging_enabled', True)
        self.declare_parameter('measurement_log_root', '')
        self.declare_parameter('measurement_run_id', '')
        self.declare_parameter(
            'event_outbox_path',
            f'/tmp/trihouse_event_outbox_{os.getpid()}.sqlite3',
        )
        self.declare_parameter('event_outbox_max_pending', 1000)

        self.robot_id = self.get_parameter('robot_id').value
        self.event_outbox = EventOutbox(
            self.get_parameter('event_outbox_path').value,
            max_pending=int(self.get_parameter('event_outbox_max_pending').value),
        )
        # session과 sequence는 SQLite에 보존해 event inbox identity를 유지한다.
        # 단, 과거 terminal RobotStatus는 최신 상태로 replay하지 않고 보류한다.
        self.session_id = self.event_outbox.session_id
        self.runtime_id = str(uuid4())
        self.connected = False
        self.connection_generation = 0
        self.status_contexts: dict[
            int, tuple[int, tuple[object, ...], int]
        ] = {}
        self.acked_status_facts: set[tuple[tuple[object, ...], int]] = set()
        self.latest_status_payloads: dict[tuple[object, ...], dict[str, object]] = {}
        self.status_evidence_retry_at: dict[tuple[tuple[object, ...], int], float] = {}
        self.last_event_attempt: dict[str, float] = {}

        # 네트워크 thread는 ROS API를 직접 호출하지 않는다. 받은 데이터와 연결
        # 상태를 queue에 넣고, ROS timer callback인 _drain이 안전하게 처리한다.
        self.inbox: deque[dict] = deque()
        self.link_states: deque[bool] = deque()

        # 최근 message_id를 기억해 재전송된 명령을 두 번 실행하지 않는다.
        self.seen: deque[str] = deque(maxlen=256)

        # ROS 파라미터가 비어 있으면 동일 이름의 환경변수 또는 writer 기본값을 쓴다.
        log_root = self.get_parameter('measurement_log_root').value
        run_id = self.get_parameter('measurement_run_id').value
        self.measurements = MeasurementLogWriter(
            root=log_root or os.environ.get('TRIHOUSE_MEASUREMENT_LOG_ROOT'),
            run_id=run_id or os.environ.get('TRIHOUSE_MEASUREMENT_RUN_ID'),
            component='pinky_gateway',
            enabled=bool(self.get_parameter('measurement_logging_enabled').value),
        )
        # 디스크 오류가 계속 발생해도 같은 경고를 매초 반복하지 않게 한다.
        self._measurement_warning_emitted = False

        # Control Tower 접속 상태를 로봇 내부의 다른 ROS 노드에 알린다.
        self.state_pub = self.create_publisher(ConnectionState, '/trihouse/fms/state', 10)
        self.outbox_ready_pub = self.create_publisher(
            Bool, '/trihouse/fms/event_outbox_ready', 10
        )

        # 통합 로봇 상태와 작업 이벤트는 Control Tower로 보내기 위해 구독한다.
        self.create_subscription(RobotStatus, '/trihouse/status', self._status, 10)
        self.create_subscription(TaskEvent, '/trihouse/task/events', self._task_event, 10)

        # 검증된 운송 명령은 fleet_node가 제공하는 ROS action으로 전달한다.
        self.transport = ActionClient(self, ExecuteTransport, '/trihouse/transport/execute')

        # 비상 요청과 접근 금지 구역은 해당 로컬 안전 노드에 ROS 메시지로 넘긴다.
        self.emergency_pub = self.create_publisher(Bool, '/trihouse/safety/emergency_request', 10)
        self.keep_out_pub = self.create_publisher(KeepOutZone, '/trihouse/safety/keep_out_zones', 10)
        self.clear_emergency = self.create_client(ClearEmergency, '/trihouse/safety/clear_emergency')

        # NDJSON client는 별도 thread에서 재접속하며 수신 결과만 queue에 추가한다.
        self.link = NdjsonClient(
            self.get_parameter('control_host').value,
            int(self.get_parameter('control_port').value),
            self.inbox.append,
            self.link_states.append,
        )
        self.link.start()

        # 20 Hz로 queue를 비우고, 2초마다 연결 생존 확인 메시지를 보낸다.
        self.create_timer(0.05, self._drain)
        self.create_timer(2.0, self._heartbeat)
        self.create_timer(0.25, self._flush_event_outbox)

    def _publish_link_state(self, connected: bool) -> None:
        """Control Tower 연결 상태를 ROS에 발행하고 접속 직후 로봇을 등록한다."""
        # ACK는 TCP connection 하나에서만 유효하다. reconnect 때 이전 ACK로
        # event가 먼저 풀리지 않도록 generation과 모든 volatile 증거를 비운다.
        self.connection_generation += 1
        self.status_contexts.clear()
        self.acked_status_facts.clear()
        self.status_evidence_retry_at.clear()
        self.connected = connected
        message = ConnectionState()
        message.stamp = self.get_clock().now().to_msg()
        message.robot_id = self.robot_id
        message.state = (
            ConnectionState.STATE_ONLINE
            if connected
            else ConnectionState.STATE_OFFLINE
        )
        message.detail = (
            'control tower connected'
            if connected
            else 'control tower disconnected'
        )
        self.state_pub.publish(message)

        # 새 TCP 연결마다 hello를 보내 Control Tower가 연결 주체를 식별하게 한다.
        if connected:
            self.link.send(
                {
                    'type': 'hello',
                    'schema_version': 3,
                    'robot_id': self.robot_id,
                    'session_id': self.session_id,
                }
            )

    def _status(self, message: RobotStatus) -> None:
        """최신 RobotStatus를 관제로 보내고 같은 내용을 배터리 측정 파일에 남긴다."""
        status_sequence = self.event_outbox.next_status_sequence()
        payload = build_robot_status_payload(
            message,
            sent_at_ns=self.get_clock().now().nanoseconds,
            session_id=self.session_id,
            sequence=status_sequence,
        )
        if message.task_context.active:
            context = _context_identity(payload['task_context'])
            decorated_payload = {
                **payload,
                '_runtime_id': self.runtime_id,
                '_captured_monotonic': monotonic(),
            }
            self.latest_status_payloads[context] = decorated_payload
            self.event_outbox.attach_status_evidence(decorated_payload)
            if self.connected:
                self.status_contexts[status_sequence] = (
                    self.connection_generation,
                    context,
                    int(payload['navigation_state']),
                )

        # 연결이 끊겨 있으면 NdjsonClient.send가 조용히 반환하고 다음 상태를 기다린다.
        self.link.send(payload)

        # 로봇별 파일로 분리해 여러 Pinky의 로그가 한 파일에 섞이지 않게 한다.
        written = self.measurements.write(
            f"battery_telemetry_{_stream_robot_id(message.robot_id)}", payload
        )

        # 측정 기록 실패는 로봇 운행을 막지 않으며 최초 한 번만 경고한다.
        if not written and not self._measurement_warning_emitted:
            self.get_logger().warning(
                'battery measurement log write failed; robot control continues'
            )
            self._measurement_warning_emitted = True

    def _task_event(self, message: TaskEvent) -> None:
        """로봇에서 발생한 작업 단계 이벤트를 Control Tower에 전달한다."""
        payload = build_task_event_payload(message, session_id=self.session_id)
        self.event_outbox.enqueue(
            payload,
            status_payload=(
                self.latest_status_payloads[
                    _context_identity(payload['task_context'])
                ]
                if _context_identity(payload['task_context'])
                in self.latest_status_payloads else None
            ),
        )

    def _flush_event_outbox(self) -> None:
        """matching RobotStatus ACK 뒤에만 미확인 event를 같은 ID로 재전송한다."""
        self.outbox_ready_pub.publish(Bool(data=not self.event_outbox.is_full))
        if not self.connected:
            return
        now = monotonic()
        for payload, status_payload in self.event_outbox.pending_records():
            event_id = str(payload['event_id'])
            context = _context_identity(payload['task_context'])
            expected_state = _event_required_navigation_state(
                str(payload.get('event_type', ''))
            )
            if expected_state is None or status_payload is None:
                continue
            if not _status_evidence_is_current(
                status_payload, runtime_id=self.runtime_id, now=now,
            ):
                continue
            if (context, expected_state) not in self.acked_status_facts:
                retry_key = (context, expected_state)
                if now - self.status_evidence_retry_at.get(retry_key, 0.0) >= 0.25:
                    sequence = self.event_outbox.next_status_sequence()
                    wire_status = {
                        key: value for key, value in status_payload.items()
                        if not key.startswith('_')
                    }
                    replay_payload = _with_replay_sequence(
                        wire_status,
                        sequence=sequence,
                        sent_at_ns=self.get_clock().now().nanoseconds,
                    )
                    self.status_contexts[sequence] = (
                        self.connection_generation, context, expected_state,
                    )
                    self.link.send(replay_payload)
                    self.status_evidence_retry_at[retry_key] = now
                continue
            if now - self.last_event_attempt.get(event_id, 0.0) < 1.0:
                continue
            self.link.send(payload)
            self.event_outbox.mark_attempted(event_id)
            self.last_event_attempt[event_id] = now

    def _heartbeat(self) -> None:
        """상태 변화가 없어도 연결 생존 여부를 확인할 heartbeat를 보낸다."""
        self.link.send(
            {
                'type': 'heartbeat',
                'schema_version': 3,
                'robot_id': self.robot_id,
                'session_id': self.session_id,
            }
        )

    def _drain(self) -> None:
        """네트워크 thread의 queue를 ROS executor 문맥에서 순서대로 처리한다."""
        # 연결/해제 상태를 먼저 ROS topic으로 반영한다.
        while self.link_states:
            self._publish_link_state(self.link_states.popleft())

        # Control Tower에서 받은 JSON 명령을 종류별 handler로 분기한다.
        while self.inbox:
            payload = self.inbox.popleft()
            response_kind = classify_gateway_response(payload)
            if response_kind == 'ack':
                if payload.get('action') == 'robot_status':
                    sequence = payload.get('sequence')
                    if isinstance(sequence, int):
                        evidence = self.status_contexts.pop(sequence, None)
                        if (
                            evidence is not None
                            and evidence[0] == self.connection_generation
                        ):
                            self.acked_status_facts.add((evidence[1], evidence[2]))
                elif payload.get('action') == 'task_event':
                    event_id = payload.get('event_id')
                    if isinstance(event_id, str):
                        self.event_outbox.acknowledge(event_id)
                        self.last_event_attempt.pop(event_id, None)
                continue
            if response_kind == 'event_rejected':
                event_id = payload.get('event_id')
                if isinstance(event_id, str):
                    self.event_outbox.reject(
                        event_id, str(payload.get('reason_code', 'UNKNOWN'))
                    )
                    self.last_event_attempt.pop(event_id, None)
                self.get_logger().error(
                    'FMS rejected telemetry/event: '
                    f"{payload.get('reason_code', 'UNKNOWN')}"
                )
                continue
            if payload.get('type') in ('emergency_request', 'clear_emergency'):
                self._handle_emergency(payload)
                continue
            if payload.get('type') == 'keep_out_zone':
                self._handle_keep_out_zone(payload)
                continue
            if payload.get('type') == 'clear_keep_out_zone':
                self._clear_keep_out_zone(payload)
                continue

            # 나머지 입력은 운송 명령 계약에 맞는지 엄격히 검증한다.
            try:
                command = parse_transport_command(payload)
            except ProtocolError as error:
                self.link.send(
                    {
                        'type': 'command_rejected',
                        'robot_id': self.robot_id,
                        'detail': str(error),
                    }
                )
                continue

            # 같은 message_id가 다시 오면 실행하지 않고 duplicate ACK만 보낸다.
            if command.message_id in self.seen:
                self.link.send(
                    {
                        'type': 'command_ack',
                        'robot_id': self.robot_id,
                        'message_id': command.message_id,
                        'duplicate': True,
                    }
                )
                continue

            if self.event_outbox.is_full:
                self.link.send(
                    {
                        'type': 'command_rejected',
                        'robot_id': self.robot_id,
                        'message_id': command.message_id,
                        'detail': 'task event outbox capacity reached',
                    }
                )
                continue

            self.seen.append(command.message_id)
            self._send_transport(command)

    def _handle_emergency(self, payload: dict) -> None:
        """비상 요청은 topic으로, 비상 해제는 승인 service로 전달한다."""
        try:
            command = parse_emergency_command(payload)
        except ProtocolError as error:
            self.link.send(
                {
                    'type': 'command_rejected',
                    'robot_id': self.robot_id,
                    'detail': str(error),
                }
            )
            return

        if command.message_id in self.seen:
            self.link.send(
                {
                    'type': 'command_ack',
                    'robot_id': self.robot_id,
                    'message_id': command.message_id,
                    'duplicate': True,
                }
            )
            return

        self.seen.append(command.message_id)

        # 비상 정지는 즉시 로컬 Safety Supervisor에 요청한다.
        if command.kind == 'emergency_request':
            self.emergency_pub.publish(Bool(data=True))
            self.link.send(
                {
                    'type': 'command_ack',
                    'robot_id': self.robot_id,
                    'message_id': command.message_id,
                    'accepted': True,
                }
            )
            return

        # 비상 해제는 operator 정보 검증 후 로컬 service가 최종 승인한다.
        if not self.clear_emergency.service_is_ready():
            self.link.send(
                {
                    'type': 'command_rejected',
                    'robot_id': self.robot_id,
                    'message_id': command.message_id,
                    'detail': 'clear emergency service unavailable',
                }
            )
            return

        request = ClearEmergency.Request()
        request.robot_id = self.robot_id
        request.operator_id = command.operator_id
        request.request_id = command.message_id
        request.reason = command.reason
        future = self.clear_emergency.call_async(request)
        future.add_done_callback(
            lambda result: self._clear_response(command.message_id, result)
        )

    def _handle_keep_out_zone(self, payload: dict) -> None:
        """관제가 지정한 polygon을 로컬 접근 금지 구역 topic으로 발행한다."""
        try:
            command = parse_keep_out_zone(payload)
        except ProtocolError as error:
            self.link.send(
                {
                    'type': 'command_rejected',
                    'robot_id': self.robot_id,
                    'detail': str(error),
                }
            )
            return

        if command.message_id in self.seen:
            self.link.send(
                {
                    'type': 'command_ack',
                    'robot_id': self.robot_id,
                    'message_id': command.message_id,
                    'duplicate': True,
                }
            )
            return

        self.seen.append(command.message_id)

        message = KeepOutZone()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = 'map'
        message.zone_id = command.zone_id
        message.polygon.points = [
            Point32(x=x, y=y, z=0.0) for x, y in command.points
        ]
        message.reason = command.reason

        # valid_for_s가 0이면 별도 만료시각을 설정하지 않는다.
        if command.valid_for_s > 0:
            message.valid_until = (
                self.get_clock().now() + Duration(seconds=command.valid_for_s)
            ).to_msg()

        self.keep_out_pub.publish(message)
        self.link.send(
            {
                'type': 'command_ack',
                'robot_id': self.robot_id,
                'message_id': command.message_id,
                'accepted': True,
            }
        )

    def _clear_keep_out_zone(self, payload: dict) -> None:
        """기존 접근 금지 구역을 즉시 만료시키는 메시지를 발행한다."""
        try:
            command = parse_clear_keep_out_zone(payload)
        except ProtocolError as error:
            self.link.send(
                {
                    'type': 'command_rejected',
                    'robot_id': self.robot_id,
                    'detail': str(error),
                }
            )
            return

        if command.message_id in self.seen:
            self.link.send(
                {
                    'type': 'command_ack',
                    'robot_id': self.robot_id,
                    'message_id': command.message_id,
                    'duplicate': True,
                }
            )
            return

        self.seen.append(command.message_id)

        # 동일한 zone_id에 현재 시각을 만료시각으로 넣어 제거를 표현한다.
        message = KeepOutZone()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = 'map'
        message.zone_id = command.zone_id
        message.reason = f'cleared by {command.operator_id}'
        message.valid_until = self.get_clock().now().to_msg()
        self.keep_out_pub.publish(message)
        self.link.send(
            {
                'type': 'command_ack',
                'robot_id': self.robot_id,
                'message_id': command.message_id,
                'accepted': True,
            }
        )

    def _clear_response(self, message_id: str, future: object) -> None:
        """비상 해제 service의 비동기 결과를 Control Tower ACK로 변환한다."""
        response = future.result()
        self.link.send(
            {
                'type': 'command_ack',
                'robot_id': self.robot_id,
                'message_id': message_id,
                'accepted': response.accepted,
                'detail': response.message,
            }
        )

    def _send_transport(self, command: TransportCommand) -> None:
        """검증된 NDJSON 운송 명령을 ExecuteTransport action goal로 변환한다."""
        # action server가 아직 준비되지 않았다면 명령을 보류하지 않고 거절한다.
        if not self.transport.wait_for_server(timeout_sec=0.0):
            self.link.send(
                {
                    'type': 'command_rejected',
                    'robot_id': self.robot_id,
                    'message_id': command.message_id,
                    'detail': 'transport action unavailable',
                }
            )
            return

        goal = ExecuteTransport.Goal()
        context = command.task_context
        goal.task_context.active = context.active
        goal.task_context.job_id = context.job_id
        goal.task_context.job_step_id = context.job_step_id
        goal.task_context.assignment_revision = context.assignment_revision
        goal.task_context.rmf_task_id = context.rmf_task_id
        goal.task_context.command_id = context.command_id
        goal.task_context.map_revision = context.map_revision
        goal.task_context.command_source = context.command_source
        goal.dropoff_location_id = command.dropoff_location_id
        goal.destination_code = command.destination_code
        goal.requires_precise_stop = command.requires_precise_stop
        goal.dropoff_pose.header.frame_id = command.frame_id
        goal.dropoff_pose.pose.position.x = command.x
        goal.dropoff_pose.pose.position.y = command.y

        # 평면 yaw를 geometry_msgs/Quaternion의 z, w 성분으로 변환한다.
        goal.dropoff_pose.pose.orientation = Quaternion(
            z=math.sin(command.yaw / 2),
            w=math.cos(command.yaw / 2),
        )

        # 문자열 mode는 action 메시지가 정의한 MODE_* 상수로 대응시킨다.
        goal.mode = getattr(ExecuteTransport.Goal, f'MODE_{command.mode}')
        future = self.transport.send_goal_async(goal)
        future.add_done_callback(
            lambda result: self._goal_response(command.message_id, result)
        )

    def _goal_response(self, message_id: str, future: object) -> None:
        """action server의 goal 수락 여부를 Control Tower ACK로 전달한다."""
        handle = future.result()
        self.link.send(
            {
                'type': 'command_ack',
                'robot_id': self.robot_id,
                'message_id': message_id,
                'accepted': bool(handle.accepted),
            }
        )

    def destroy_node(self) -> bool:
        """네트워크 thread를 먼저 멈춘 뒤 ROS node 자원을 해제한다."""
        self.link.stop()
        return super().destroy_node()


def main() -> None:
    """rclpy를 초기화하고 GatewayNode를 종료 요청까지 실행한다."""
    rclpy.init()
    node = GatewayNode()

    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
