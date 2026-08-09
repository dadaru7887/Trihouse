"""부저 actuator. latch된 비상 indicator가 있는 동안에만 켠다."""
import rclpy
from rclpy.node import Node
from trihouse_interfaces.msg import IndicatorState


class BuzzerIndicatorClient(Node):
    def __init__(self) -> None:
        super().__init__('buzzer_indicator_client')
        self.declare_parameter('gpio_pin', 24)
        self.gpio = None
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM); GPIO.setup(self.get_parameter('gpio_pin').value, GPIO.OUT, initial=GPIO.LOW)
            self.gpio = GPIO
        except Exception as error:
            self.get_logger().warning(f'buzzer GPIO unavailable: {error}')
        self.create_subscription(IndicatorState, '/trihouse/indicator/state', self._apply, 10)

    def _apply(self, message: IndicatorState) -> None:
        if self.gpio is not None:
            self.gpio.output(self.get_parameter('gpio_pin').value, self.gpio.HIGH if message.state == IndicatorState.STATE_EMERGENCY else self.gpio.LOW)


def main() -> None:
    rclpy.init(); node = BuzzerIndicatorClient()
    try: rclpy.spin(node)
    finally:
        if node.gpio is not None: node.gpio.cleanup()
        node.destroy_node(); rclpy.shutdown()
