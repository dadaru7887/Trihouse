"""vendor 초음파 topic을 Trihouse namespace로 옮기는 adapter."""
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Range


class UltrasonicAdapter(Node):
    def __init__(self) -> None:
        super().__init__('ultrasonic_adapter')
        self.publisher = self.create_publisher(Range, '/trihouse/proximity/front', 10)
        self.create_subscription(Range, '/us_sensor/range', self.publisher.publish, 10)


def main() -> None:
    rclpy.init(); node = UltrasonicAdapter()
    try: rclpy.spin(node)
    finally: node.destroy_node(); rclpy.shutdown()
