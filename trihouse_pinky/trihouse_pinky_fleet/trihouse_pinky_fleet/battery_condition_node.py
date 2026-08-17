"""BatteryState를 검증해 BatteryCondition을 발행하는 ROS 2 노드."""

from time import monotonic

import rclpy
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)
from sensor_msgs.msg import BatteryState
from trihouse_interfaces.msg import BatteryCondition

from .battery_condition import BatteryConditionTracker, BatteryObservation


class BatteryConditionNode(Node):
    """배터리 원본의 유효성과 freshness를 1 Hz 및 변경 즉시 보고한다."""

    def __init__(self) -> None:
        super().__init__('battery_condition_node')
        self.declare_parameter('robot_id', 'PK_01')
        self.declare_parameter('startup_timeout_s', 5.0)
        self.declare_parameter('telemetry_timeout_s', 3.0)

        self.robot_id = str(self.get_parameter('robot_id').value)
        self.tracker = BatteryConditionTracker(
            started_at=monotonic(),
            startup_timeout_s=float(self.get_parameter('startup_timeout_s').value),
            telemetry_timeout_s=float(self.get_parameter('telemetry_timeout_s').value),
        )
        self._last_published: BatteryObservation | None = None

        qos = QoSProfile(
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=5,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.VOLATILE,
        )
        self.publisher = self.create_publisher(
            BatteryCondition, 'trihouse/battery/condition', qos
        )
        self.create_subscription(
            BatteryState, 'trihouse/battery', self._on_battery, qos
        )
        self.create_timer(1.0, self._publish_heartbeat)

    def _on_battery(self, message: BatteryState) -> None:
        observation = self.tracker.ingest(
            percentage=float(message.percentage),
            present=bool(message.present),
            power_supply_status=int(message.power_supply_status),
            received_at=monotonic(),
        )
        if observation != self._last_published:
            self._publish(observation)

    def _publish_heartbeat(self) -> None:
        self._publish(self.tracker.evaluate(now=monotonic()))

    def _publish(self, observation: BatteryObservation) -> None:
        message = BatteryCondition()
        message.stamp = self.get_clock().now().to_msg()
        message.robot_id = self.robot_id
        message.percentage = observation.percentage
        message.present = observation.present
        message.power_supply_status = observation.power_supply_status
        message.measurement_valid = observation.measurement_valid
        message.has_valid_sample = observation.has_valid_sample
        message.telemetry_fresh = observation.telemetry_fresh
        self.publisher.publish(message)
        self._last_published = observation


def main() -> None:
    rclpy.init()
    node = BatteryConditionNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
