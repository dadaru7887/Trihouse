"""공용 위험 indicator를 Pinky-Pro `/set_led` service 호출로 바꾸는 client."""
import rclpy
from rclpy.node import Node
from trihouse_interfaces.msg import IndicatorState
from pinky_interfaces.srv import SetLed


class LedIndicatorClient(Node):
    COLORS = {IndicatorState.STATE_OFF: (0, 0, 0), IndicatorState.STATE_PERSON_DETECTED: (255, 128, 0), IndicatorState.STATE_EMERGENCY: (255, 0, 0)}
    def __init__(self) -> None:
        super().__init__('led_indicator_client')
        self.client = self.create_client(SetLed, 'set_led')
        self.create_subscription(IndicatorState, 'trihouse/indicator/state', self._apply, 10)

    def _apply(self, message: IndicatorState) -> None:
        if not self.client.service_is_ready():
            self.get_logger().warning('/set_led is unavailable; indicator is not applied')
            return
        red, green, blue = self.COLORS.get(message.state, self.COLORS[IndicatorState.STATE_OFF])
        request = SetLed.Request(); request.command = 'clear' if message.state == IndicatorState.STATE_OFF else 'fill'; request.r = red; request.g = green; request.b = blue
        self.client.call_async(request)


def main() -> None:
    rclpy.init(); node = LedIndicatorClient()
    try: rclpy.spin(node)
    finally: node.destroy_node(); rclpy.shutdown()
