"""vendor 배터리 topic을 Trihouse fleet 계약으로 바꾸는 ROS adapter."""
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import BatteryState


class BatteryAdapter(Node):
    def __init__(self) -> None:
        super().__init__('battery_adapter')
        self.publisher = self.create_publisher(BatteryState, '/trihouse/battery', 10)
        self.create_subscription(BatteryState, '/batt_state', self.publisher.publish, 10)


def main() -> None:
    rclpy.init(); node = BatteryAdapter()
    try: rclpy.spin(node)
    finally: node.destroy_node(); rclpy.shutdown()
