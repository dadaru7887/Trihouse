"""fleet action server가 구독할 readiness gate를 ROS topic으로 발행한다."""

from time import monotonic

import rclpy
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from nav_msgs.msg import Odometry
from trihouse_interfaces.msg import Readiness

from .readiness import ReadinessInputs, evaluate_readiness


class ReadinessChecker(Node):
    def __init__(self) -> None:
        super().__init__('readiness_checker')
        self.declare_parameter('robot_id', 'PK_01'); self.declare_parameter('sensor_timeout_s', 1.0)
        self.robot_id = self.get_parameter('robot_id').value
        self.timeout = float(self.get_parameter('sensor_timeout_s').value)
        self.last_scan, self.last_odom = 0.0, 0.0
        self.create_subscription(LaserScan, '/scan', lambda _: self._mark('scan'), 10)
        self.create_subscription(Odometry, '/odom', lambda _: self._mark('odom'), 10)
        self.publisher = self.create_publisher(Readiness, '/trihouse/readiness', 10)
        self.nav = ActionClient(self, NavigateToPose, '/navigate_to_pose')
        self.create_timer(1.0, self._publish)

    def _mark(self, source: str) -> None:
        if source == 'scan': self.last_scan = monotonic()
        else: self.last_odom = monotonic()

    def _publish(self) -> None:
        now = monotonic()
        result = evaluate_readiness(ReadinessInputs(now - self.last_scan <= self.timeout, now - self.last_odom <= self.timeout, self.nav.server_is_ready()))
        message = Readiness(); message.stamp = self.get_clock().now().to_msg(); message.robot_id = self.robot_id
        message.state = Readiness.STATE_READY if result.ready else Readiness.STATE_NOT_READY
        message.missing_interfaces = list(result.missing); message.details = ['base transport prerequisites']
        self.publisher.publish(message)


def main() -> None:
    rclpy.init(); node = ReadinessChecker()
    try: rclpy.spin(node)
    finally: node.destroy_node(); rclpy.shutdown()
