"""Gazebo에서만 쓰는 Pinky 하드웨어 입력의 명시적 대체 publisher."""
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import BatteryState, Range


class SimHardware(Node):
    def __init__(self) -> None:
        super().__init__('sim_hardware')
        self.declare_parameter('front_distance_m', 3.0); self.declare_parameter('battery_percentage', 1.0)
        self.range_pub = self.create_publisher(Range, '/trihouse/proximity/front', 10)
        self.battery_pub = self.create_publisher(BatteryState, '/trihouse/battery', 10)
        self.create_timer(0.1, self._publish)

    def _publish(self) -> None:
        distance = float(self.get_parameter('front_distance_m').value)
        proximity = Range(); proximity.header.stamp = self.get_clock().now().to_msg(); proximity.header.frame_id = 'ultrasonic_link'
        proximity.radiation_type = Range.ULTRASOUND; proximity.min_range = 0.02; proximity.max_range = 3.0; proximity.range = distance
        battery = BatteryState(); battery.header.stamp = proximity.header.stamp; battery.percentage = float(self.get_parameter('battery_percentage').value)
        self.range_pub.publish(proximity); self.battery_pub.publish(battery)


def main() -> None:
    rclpy.init(); node = SimHardware()
    try: rclpy.spin(node)
    finally: node.destroy_node(); rclpy.shutdown()
