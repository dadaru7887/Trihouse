"""SR_23·54의 최종 Pinky 속도 gate를 ROS topic/service로 연결하는 node."""

from time import monotonic
from math import hypot

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from sensor_msgs.msg import LaserScan, Range
from nav_msgs.msg import Odometry
from std_msgs.msg import Bool
from trihouse_interfaces.msg import ConnectionState, IndicatorState, KeepOutZone, PersonDetection, SafetyState
from trihouse_interfaces.srv import ClearEmergency

from .geometry import point_in_polygon
from .policy import MotionCommand, SafetyConfig, SafetyInputs, apply_safety_gate


class SafetySupervisor(Node):
    """The only operational publisher for the motor `/cmd_vel` topic."""
    def __init__(self) -> None:
        super().__init__('safety_supervisor')
        self.declare_parameter('robot_id', 'PK-01')
        self.declare_parameter('sensor_timeout_s', 0.5)
        self.declare_parameter('stop_distance_m', 0.30)
        self.declare_parameter('slow_distance_m', 0.70)
        self.declare_parameter('slow_linear_speed_mps', 0.08)
        self.declare_parameter('require_ultrasonic', True)
        self.declare_parameter('person_protective_distance_m', 1.0)
        self.robot_id = self.get_parameter('robot_id').value
        self.sensor_timeout_s = float(self.get_parameter('sensor_timeout_s').value)
        self.config = SafetyConfig(float(self.get_parameter('stop_distance_m').value), float(self.get_parameter('slow_distance_m').value), float(self.get_parameter('slow_linear_speed_mps').value), float(self.get_parameter('person_protective_distance_m').value))
        self.require_ultrasonic = bool(self.get_parameter('require_ultrasonic').value)
        self.nav = MotionCommand(0.0, 0.0)
        self.dock: MotionCommand | None = None
        self.front_range: float | None = None
        self.scan_range: float | None = None
        self.person_detected = False
        self.person_distance = None
        self.person_until = 0.0
        self.keep_out_zones: dict[str, KeepOutZone] = {}
        self.position: tuple[float, float] | None = None
        self.emergency_latched = False
        self.control_link_online = False
        self.last_sensor_at = 0.0
        self.last_range_at = 0.0
        self.last_scan_at = 0.0
        self.create_subscription(Twist, '/cmd_vel_nav', self._on_nav, 10)
        self.create_subscription(Twist, '/cmd_vel_dock', self._on_dock, 10)
        self.create_subscription(Range, '/trihouse/proximity/front', self._on_range, 10)
        self.create_subscription(LaserScan, '/scan', self._on_scan, 10)
        self.create_subscription(PersonDetection, '/trihouse/vision/person_detection/base', self._on_person, 10)
        self.create_subscription(KeepOutZone, '/trihouse/safety/keep_out_zones', self._on_keep_out, 10)
        self.create_subscription(Odometry, '/odom', self._on_odom, 10)
        self.create_subscription(ConnectionState, '/trihouse/fms/state', self._on_connection, 10)
        # Vision detects; the Control Tower/Safety authority explicitly requests emergency.
        self.create_subscription(Bool, '/trihouse/safety/emergency_request', self._on_emergency_request, 10)
        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.state_pub = self.create_publisher(SafetyState, '/trihouse/safety/state', 10)
        self.indicator_pub = self.create_publisher(IndicatorState, '/trihouse/indicator/state', 10)
        self.create_service(ClearEmergency, '/trihouse/safety/clear_emergency', self._clear_emergency)
        self.create_timer(0.05, self._publish)

    def _on_nav(self, message: Twist) -> None:
        self.nav = MotionCommand(message.linear.x, message.angular.z)

    def _on_dock(self, message: Twist) -> None:
        self.dock = MotionCommand(message.linear.x, message.angular.z)

    def _on_range(self, message: Range) -> None:
        self.front_range = message.range; self.last_range_at = monotonic(); self.last_sensor_at = self.last_range_at

    def _on_scan(self, message: LaserScan) -> None:
        finite = [value for value in message.ranges if message.range_min <= value <= message.range_max]
        self.scan_range = min(finite) if finite else None
        self.last_scan_at = monotonic(); self.last_sensor_at = self.last_scan_at

    def _on_person(self, message: PersonDetection) -> None:
        self.person_detected = message.confidence > 0.0
        position = message.pose.pose.position
        self.person_distance = hypot(position.x, position.y)
        self.person_until = monotonic() + max(message.ttl_ms, 1) / 1000.0

    def _on_keep_out(self, message: KeepOutZone) -> None:
        self.keep_out_zones[message.zone_id] = message

    def _on_odom(self, message: Odometry) -> None:
        pose = message.pose.pose.position
        self.position = (pose.x, pose.y)

    def _on_connection(self, message: ConnectionState) -> None:
        """관제 재연결이 곧 자동 재개가 되지 않도록 online 상태만 safety 입력으로 반영한다."""
        self.control_link_online = message.state == ConnectionState.STATE_ONLINE

    def _on_emergency_request(self, message: Bool) -> None:
        if message.data:
            self.emergency_latched = True

    def _clear_emergency(self, request: ClearEmergency.Request, response: ClearEmergency.Response) -> ClearEmergency.Response:
        if request.robot_id != self.robot_id or not request.operator_id:
            response.accepted, response.message = False, 'robot_id or operator_id is invalid'
            return response
        self.emergency_latched = False
        response.accepted, response.message = True, 'emergency latch cleared; fleet must start return inspection'
        response.cleared_at = self.get_clock().now().to_msg()
        return response

    def _publish(self) -> None:
        desired = self.dock if self.dock is not None else self.nav
        person_detected = self.person_detected and monotonic() <= self.person_until
        now = monotonic()
        scan_fresh = now - self.last_scan_at <= self.sensor_timeout_s
        range_fresh = now - self.last_range_at <= self.sensor_timeout_s
        inputs = SafetyInputs(sensor_fresh=scan_fresh and (range_fresh or not self.require_ultrasonic),
                              front_distance_m=self._front_distance(), person_detected=False,
                              person_distance_m=self.person_distance if person_detected else None,
                              keep_out=self._in_keep_out_zone(), emergency_latched=self.emergency_latched,
                              control_link_fresh=self.control_link_online)
        decision = apply_safety_gate(desired, inputs, self.config)
        cmd = Twist(); cmd.linear.x = decision.command.linear_x; cmd.angular.z = decision.command.angular_z
        self.cmd_pub.publish(cmd)
        state = SafetyState(); state.stamp = self.get_clock().now().to_msg(); state.robot_id = self.robot_id
        state.state = int(decision.level); state.latched = self.emergency_latched; state.source = 'safety_supervisor'; state.detail = decision.reason
        self.state_pub.publish(state)
        indicator = IndicatorState(); indicator.stamp = state.stamp; indicator.robot_id = self.robot_id
        indicator.state = IndicatorState.STATE_EMERGENCY if self.emergency_latched else (IndicatorState.STATE_PERSON_DETECTED if person_detected and self.person_distance is not None and self.person_distance <= self.config.person_protective_distance_m else IndicatorState.STATE_OFF)
        indicator.source = 'safety_supervisor'; indicator.detail = decision.reason
        self.indicator_pub.publish(indicator)

    def _front_distance(self) -> float | None:
        now = monotonic()
        values = [value for value, timestamp in ((self.front_range, self.last_range_at), (self.scan_range, self.last_scan_at)) if value is not None and now - timestamp <= self.sensor_timeout_s]
        return min(values) if values else None

    def _in_keep_out_zone(self) -> bool:
        if self.position is None:
            return False
        now = self.get_clock().now().nanoseconds
        for zone in self.keep_out_zones.values():
            valid_until = zone.valid_until.sec * 1_000_000_000 + zone.valid_until.nanosec
            if valid_until and valid_until < now:
                continue
            points = tuple((point.x, point.y) for point in zone.polygon.points)
            if len(points) >= 3 and point_in_polygon(*self.position, points):
                return True
        return False


def main() -> None:
    rclpy.init(); node = SafetySupervisor()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node(); rclpy.shutdown()
