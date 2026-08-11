"""Control Tower NDJSON 명령을 검증 후 ExecuteTransport action으로 바꾸는 경계."""

import math
from collections import deque

import rclpy
from geometry_msgs.msg import Point32, Quaternion
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.node import Node
from std_msgs.msg import Bool
from trihouse_interfaces.action import ExecuteTransport
from trihouse_interfaces.msg import ConnectionState, KeepOutZone, RobotStatus, TaskEvent
from trihouse_interfaces.srv import ClearEmergency

from .ndjson_client import NdjsonClient
from .protocol import ProtocolError, TransportCommand, parse_clear_keep_out_zone, parse_emergency_command, parse_keep_out_zone, parse_transport_command


class GatewayNode(Node):
    def __init__(self) -> None:
        super().__init__('fleet_gateway')
        self.declare_parameter('robot_id', 'PK-01'); self.declare_parameter('control_host', '127.0.0.1'); self.declare_parameter('control_port', 8788)
        self.robot_id = self.get_parameter('robot_id').value; self.inbox: deque[dict] = deque(); self.link_states: deque[bool] = deque(); self.seen: deque[str] = deque(maxlen=256)
        self.state_pub = self.create_publisher(ConnectionState, '/trihouse/fms/state', 10)
        self.create_subscription(RobotStatus, '/trihouse/status', self._status, 10)
        self.create_subscription(TaskEvent, '/trihouse/task/events', self._task_event, 10)
        self.transport = ActionClient(self, ExecuteTransport, '/trihouse/transport/execute')
        self.emergency_pub = self.create_publisher(Bool, '/trihouse/safety/emergency_request', 10)
        self.keep_out_pub = self.create_publisher(KeepOutZone, '/trihouse/safety/keep_out_zones', 10)
        self.clear_emergency = self.create_client(ClearEmergency, '/trihouse/safety/clear_emergency')
        self.link = NdjsonClient(self.get_parameter('control_host').value, int(self.get_parameter('control_port').value), self.inbox.append, self.link_states.append)
        self.link.start(); self.create_timer(0.05, self._drain); self.create_timer(2.0, self._heartbeat)

    def _publish_link_state(self, connected: bool) -> None:
        message = ConnectionState(); message.stamp = self.get_clock().now().to_msg(); message.robot_id = self.robot_id
        message.state = ConnectionState.STATE_ONLINE if connected else ConnectionState.STATE_OFFLINE
        message.detail = 'control tower connected' if connected else 'control tower disconnected'
        self.state_pub.publish(message)
        if connected: self.link.send({'type': 'hello', 'schema_version': 1, 'robot_id': self.robot_id})

    def _status(self, message: RobotStatus) -> None:
        self.link.send({'type': 'robot_status', 'schema_version': 1, 'robot_id': message.robot_id, 'sent_at_ns': self.get_clock().now().nanoseconds, 'job_id': message.current_job_id, 'job_step_id': message.current_job_step_id, 'ready': message.ready, 'battery_percentage': message.battery_percentage, 'safety_state': message.safety.state, 'cargo_state': message.cargo.state, 'errors': list(message.errors)})

    def _task_event(self, message: TaskEvent) -> None:
        self.link.send({'type': 'task_event', 'schema_version': 1, 'message_id': message.event_id, 'robot_id': message.robot_id, 'job_id': message.job_id, 'job_step_id': message.job_step_id, 'event_type': message.event_type, 'detail': message.detail})

    def _heartbeat(self) -> None:
        self.link.send({'type': 'heartbeat', 'schema_version': 1, 'robot_id': self.robot_id})

    def _drain(self) -> None:
        while self.link_states:
            self._publish_link_state(self.link_states.popleft())
        while self.inbox:
            payload = self.inbox.popleft()
            if payload.get('type') in ('emergency_request', 'clear_emergency'):
                self._handle_emergency(payload); continue
            if payload.get('type') == 'keep_out_zone':
                self._handle_keep_out_zone(payload); continue
            if payload.get('type') == 'clear_keep_out_zone':
                self._clear_keep_out_zone(payload); continue
            try: command = parse_transport_command(payload)
            except ProtocolError as error:
                self.link.send({'type': 'command_rejected', 'robot_id': self.robot_id, 'detail': str(error)}); continue
            if command.message_id in self.seen:
                self.link.send({'type': 'command_ack', 'robot_id': self.robot_id, 'message_id': command.message_id, 'duplicate': True}); continue
            self.seen.append(command.message_id); self._send_transport(command)

    def _handle_emergency(self, payload: dict) -> None:
        try: command = parse_emergency_command(payload)
        except ProtocolError as error:
            self.link.send({'type': 'command_rejected', 'robot_id': self.robot_id, 'detail': str(error)}); return
        if command.message_id in self.seen:
            self.link.send({'type': 'command_ack', 'robot_id': self.robot_id, 'message_id': command.message_id, 'duplicate': True}); return
        self.seen.append(command.message_id)
        if command.kind == 'emergency_request':
            self.emergency_pub.publish(Bool(data=True))
            self.link.send({'type': 'command_ack', 'robot_id': self.robot_id, 'message_id': command.message_id, 'accepted': True})
            return
        if not self.clear_emergency.service_is_ready():
            self.link.send({'type': 'command_rejected', 'robot_id': self.robot_id, 'message_id': command.message_id, 'detail': 'clear emergency service unavailable'}); return
        request = ClearEmergency.Request(); request.robot_id = self.robot_id; request.operator_id = command.operator_id; request.request_id = command.message_id; request.reason = command.reason
        future = self.clear_emergency.call_async(request); future.add_done_callback(lambda result: self._clear_response(command.message_id, result))

    def _handle_keep_out_zone(self, payload: dict) -> None:
        try: command = parse_keep_out_zone(payload)
        except ProtocolError as error:
            self.link.send({'type': 'command_rejected', 'robot_id': self.robot_id, 'detail': str(error)}); return
        if command.message_id in self.seen:
            self.link.send({'type': 'command_ack', 'robot_id': self.robot_id, 'message_id': command.message_id, 'duplicate': True}); return
        self.seen.append(command.message_id)
        message = KeepOutZone(); message.header.stamp = self.get_clock().now().to_msg(); message.header.frame_id = 'map'; message.zone_id = command.zone_id
        message.polygon.points = [Point32(x=x, y=y, z=0.0) for x, y in command.points]; message.reason = command.reason
        if command.valid_for_s > 0: message.valid_until = (self.get_clock().now() + Duration(seconds=command.valid_for_s)).to_msg()
        self.keep_out_pub.publish(message)
        self.link.send({'type': 'command_ack', 'robot_id': self.robot_id, 'message_id': command.message_id, 'accepted': True})

    def _clear_keep_out_zone(self, payload: dict) -> None:
        try: command = parse_clear_keep_out_zone(payload)
        except ProtocolError as error:
            self.link.send({'type': 'command_rejected', 'robot_id': self.robot_id, 'detail': str(error)}); return
        if command.message_id in self.seen:
            self.link.send({'type': 'command_ack', 'robot_id': self.robot_id, 'message_id': command.message_id, 'duplicate': True}); return
        self.seen.append(command.message_id)
        message = KeepOutZone(); message.header.stamp = self.get_clock().now().to_msg(); message.header.frame_id = 'map'; message.zone_id = command.zone_id; message.reason = f'cleared by {command.operator_id}'
        message.valid_until = self.get_clock().now().to_msg()
        self.keep_out_pub.publish(message)
        self.link.send({'type': 'command_ack', 'robot_id': self.robot_id, 'message_id': command.message_id, 'accepted': True})

    def _clear_response(self, message_id: str, future: object) -> None:
        response = future.result()
        self.link.send({'type': 'command_ack', 'robot_id': self.robot_id, 'message_id': message_id, 'accepted': response.accepted, 'detail': response.message})

    def _send_transport(self, command: TransportCommand) -> None:
        if not self.transport.wait_for_server(timeout_sec=0.0):
            self.link.send({'type': 'command_rejected', 'robot_id': self.robot_id, 'message_id': command.message_id, 'detail': 'transport action unavailable'}); return
        goal = ExecuteTransport.Goal(); goal.command_id = command.message_id; goal.job_id = command.job_id; goal.job_step_id = command.job_step_id; goal.map_revision = command.map_revision
        goal.dropoff_location_id = command.dropoff_location_id; goal.destination_code = command.destination_code; goal.requires_precise_stop = command.requires_precise_stop; goal.dropoff_pose.header.frame_id = command.frame_id; goal.dropoff_pose.pose.position.x = command.x; goal.dropoff_pose.pose.position.y = command.y
        goal.dropoff_pose.pose.orientation = Quaternion(z=math.sin(command.yaw / 2), w=math.cos(command.yaw / 2))
        goal.mode = getattr(ExecuteTransport.Goal, f'MODE_{command.mode}')
        future = self.transport.send_goal_async(goal); future.add_done_callback(lambda result: self._goal_response(command.message_id, result))

    def _goal_response(self, message_id: str, future: object) -> None:
        handle = future.result()
        self.link.send({'type': 'command_ack', 'robot_id': self.robot_id, 'message_id': message_id, 'accepted': bool(handle.accepted)})

    def destroy_node(self) -> bool:
        self.link.stop()
        return super().destroy_node()


def main() -> None:
    rclpy.init(); node = GatewayNode()
    try: rclpy.spin(node)
    finally: node.destroy_node(); rclpy.shutdown()
