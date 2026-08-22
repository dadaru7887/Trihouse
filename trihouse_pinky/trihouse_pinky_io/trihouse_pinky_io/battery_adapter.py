"""vendor 배터리 topic을 Trihouse fleet 계약으로 바꾸는 ROS adapter."""
from math import isfinite

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import BatteryState
from std_msgs.msg import Float32


class BatteryAdapter(Node):
    def __init__(self) -> None:
        super().__init__('battery_adapter')
        self.percentage: float | None = None
        self.publisher = self.create_publisher(BatteryState, 'trihouse/battery', 10)
        self.create_subscription(Float32, 'battery/percent', self._on_percentage, 10)
        self.create_subscription(BatteryState, 'batt_state', self._on_battery, 10)

    def _on_percentage(self, message: Float32) -> None:
        """벤더의 0~100 퍼센트를 BatteryState 계약의 0~1 비율로 보존한다."""
        value = float(message.data)
        if isfinite(value) and 0.0 <= value <= 100.0:
            self.percentage = value / 100.0

    def _on_battery(self, message: BatteryState) -> None:
        """ADC 전압 메시지에 벤더 퍼센트와 실제 연결 여부를 합쳐 발행한다."""
        if self.percentage is not None:
            message.percentage = self.percentage
        message.present = isfinite(float(message.voltage)) and message.voltage > 0.0
        self.publisher.publish(message)


def main() -> None:
    rclpy.init(); node = BatteryAdapter()
    try: rclpy.spin(node)
    finally: node.destroy_node(); rclpy.shutdown()
