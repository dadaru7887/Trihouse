"""BatteryCondition을 BatteryPolicyState ROS snapshot으로 변환한다."""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import BatteryState
from trihouse_interfaces.msg import BatteryCondition, BatteryPolicyState

from .battery_policy import classify_battery


class BatteryPolicyNode(Node):
    def __init__(self) -> None:
        super().__init__("battery_policy_node")
        self._charging = False
        self._condition = BatteryCondition()
        self.publisher = self.create_publisher(
            BatteryPolicyState, "trihouse/battery/policy_state", 10,
        )
        self.create_subscription(
            BatteryCondition, "trihouse/battery/condition", self._on_condition, 10,
        )
        self.create_subscription(
            BatteryState, "trihouse/battery", self._on_battery, 10,
        )
        self.create_timer(1.0, self._publish)

    def _on_battery(self, message: BatteryState) -> None:
        self._charging = (
            message.power_supply_status == BatteryState.POWER_SUPPLY_STATUS_CHARGING
        )

    def _on_condition(self, message: BatteryCondition) -> None:
        self._condition = message
        self._publish()

    def _publish(self) -> None:
        condition = self._condition
        valid = (
            condition.present
            and condition.measurement_valid
            and condition.has_valid_sample
            and condition.telemetry_fresh
        )
        projection = classify_battery(
            condition.percentage, valid=valid, charging=self._charging,
        )
        states = {
            "UNKNOWN": BatteryPolicyState.STATE_UNKNOWN,
            "NORMAL": BatteryPolicyState.STATE_NORMAL,
            "LOCAL_ONLY": BatteryPolicyState.STATE_LOCAL_ONLY,
            "RETURN_REQUIRED": BatteryPolicyState.STATE_RETURN_REQUIRED,
            "CHARGING": BatteryPolicyState.STATE_CHARGING,
        }
        message = BatteryPolicyState()
        message.stamp = self.get_clock().now().to_msg()
        message.robot_id = condition.robot_id
        message.condition = condition
        message.state = states[projection.state]
        message.ready = projection.ready
        message.reason_code = projection.reason_code
        message.detail = projection.state
        self.publisher.publish(message)


def main() -> None:
    rclpy.init()
    node = BatteryPolicyNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
