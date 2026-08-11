"""실기 OMX endpoint를 검증하기 전의 안전한 adapter skeleton.

이 node는 MoveIt/gripper topic을 발행하지 않는다. 설정된 endpoint와 acknowledgements를
관찰해 진단 상태만 기록하도록 두며, 실제 endpoint 계약이 확정된 뒤에만 hardware plugin을
연결해야 한다.
"""

import rclpy
from rclpy.node import Node


class HardwareOmxAdapterSkeleton(Node):
    """확인되지 않은 실기 interface로 motion을 보내지 않는 진단 전용 skeleton이다."""

    def __init__(self) -> None:
        super().__init__("hardware_omx_adapter")
        for name in ("omx_id", "joint_state_topic", "gripper_ack_topic", "emergency_ack_topic", "payload_limit_kg"):
            self.declare_parameter(name, "" if name != "payload_limit_kg" else 0.0)
        self.create_timer(2.0, self._report_unconfigured_contract)

    def _report_unconfigured_contract(self) -> None:
        missing = [name for name in ("joint_state_topic", "gripper_ack_topic", "emergency_ack_topic") if not self.get_parameter(name).value]
        if missing:
            self.get_logger().warn("OMX hardware motion disabled; configure verified endpoints: " + ", ".join(missing))
        else:
            self.get_logger().info("OMX endpoints configured; motion remains disabled until hardware plugin is approved")


def main() -> None:
    rclpy.init()
    node = HardwareOmxAdapterSkeleton()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
