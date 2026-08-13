"""필수 Pinky telemetry로 비상 해제 후 RobotHealth를 발행한다."""

from time import monotonic

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import BatteryState, LaserScan, Range
from trihouse_interfaces.msg import CargoState, RobotHealth

from .recovery_health import RecoveryHealthInputs, evaluate_recovery_health


class RecoveryHealthNode(Node):
    def __init__(self) -> None:
        super().__init__('recovery_health')
        self.declare_parameter('robot_id', 'PK_01'); self.declare_parameter('timeout_s', 1.5)
        self.robot_id = self.get_parameter('robot_id').value; self.timeout = float(self.get_parameter('timeout_s').value)
        self.last_odom = self.last_scan = self.last_range = self.last_battery = 0.0
        self.cargo_present = False
        self.create_subscription(Odometry, '/odom', lambda _: self._mark('odom'), 10)
        self.create_subscription(LaserScan, '/scan', lambda _: self._mark('scan'), 10)
        self.create_subscription(Range, '/trihouse/proximity/front', lambda _: self._mark('range'), 10)
        self.create_subscription(BatteryState, '/trihouse/battery', lambda _: self._mark('battery'), 10)
        self.create_subscription(CargoState, '/trihouse/cargo/state', self._cargo, 10)
        self.publisher = self.create_publisher(RobotHealth, '/trihouse/health', 10)
        self.create_timer(1.0, self._publish)

    def _mark(self, component: str) -> None:
        setattr(self, f'last_{component}', monotonic())

    def _cargo(self, message: CargoState) -> None:
        self.cargo_present = message.state == CargoState.STATE_LOCKED

    def _publish(self) -> None:
        now = monotonic(); result = evaluate_recovery_health(RecoveryHealthInputs(now-self.last_odom <= self.timeout, now-self.last_scan <= self.timeout, now-self.last_range <= self.timeout, now-self.last_battery <= self.timeout, self.cargo_present))
        message = RobotHealth(); message.stamp = self.get_clock().now().to_msg(); message.robot_id = self.robot_id
        message.state = RobotHealth.STATE_OK if result.ready else RobotHealth.STATE_ERROR
        message.component_names = ['odom', 'scan', 'ultrasonic', 'battery', 'cargo']
        message.component_states = [RobotHealth.STATE_OK if name not in result.failures else RobotHealth.STATE_ERROR for name in message.component_names]
        message.details = list(result.failures)
        self.publisher.publish(message)


def main() -> None:
    rclpy.init(); node = RecoveryHealthNode()
    try: rclpy.spin(node)
    finally: node.destroy_node(); rclpy.shutdown()
