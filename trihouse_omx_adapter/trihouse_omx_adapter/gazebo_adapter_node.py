"""Gazebo 데모용 OMX 상태 adapter.

실기 OMX endpoint를 추측하지 않는다. 이 node는 공용 HandoverState/CargoState만 발행하며,
`mock_load_confirmed` parameter로 시연자가 적재 물리 확인을 명시적으로 켤 수 있다.

P0에서는 `OmxProtocolSimulator`가 같은 프로세스에서 Gateway 명령 계약을
검증하고 결정적 상태 전이를 만든다. 실제 OMX motion은 나가지 않는다.
"""

import rclpy
from rclpy.node import Node
from trihouse_interfaces.msg import CargoState, HandoverState

from .protocol_simulator import OmxProtocolSimulator


def cargo_state_for_confirmation(confirmed: bool) -> int:
    """mock 적재 확인을 공용 cargo lock 상태로 변환한다."""
    return (
        CargoState.STATE_LOCKED
        if confirmed
        else CargoState.STATE_UNLOCKED
    )


class GazeboOmxAdapter(Node):
    """Gazebo의 명시적 mock cargo 확인을 ROS 공용 상태로 바꾸는 최소 adapter다."""

    def __init__(self) -> None:
        super().__init__("gazebo_omx_adapter")
        self.declare_parameter("omx_id", "OMX-01")
        self.declare_parameter("robot_id", "PK-01")
        self.declare_parameter("job_id", "")
        self.declare_parameter("job_step_id", "")
        self.declare_parameter("station_id", "station-1")
        self.declare_parameter("mock_load_confirmed", False)
        # 시뮬레이터는 이 adapter가 대표하는 OMX 하나만 응답한다.
        self.simulator = OmxProtocolSimulator(
            omx_id=str(self.get_parameter("omx_id").value)
        )
        self.handover_pub = self.create_publisher(HandoverState, "/trihouse/handover/state", 10)
        self.cargo_pub = self.create_publisher(CargoState, "trihouse/cargo/state", 10)
        self.create_timer(0.5, self._publish)

    def _publish(self) -> None:
        confirmed = bool(self.get_parameter("mock_load_confirmed").value)
        stamp = self.get_clock().now().to_msg()
        handover = HandoverState()
        handover.stamp = stamp
        handover.robot_id = str(self.get_parameter("robot_id").value)
        handover.job_id = str(self.get_parameter("job_id").value)
        handover.job_step_id = str(self.get_parameter("job_step_id").value)
        handover.station_id = str(self.get_parameter("station_id").value)
        # HandoverState에는 WAITING 상수가 없으므로, 대기 중 요청은 REQUESTED로 표현한다.
        handover.state = HandoverState.STATE_READY if confirmed else HandoverState.STATE_REQUESTED
        handover.detail = "Gazebo mock OMX cargo confirmed" if confirmed else "Gazebo mock OMX awaiting cargo confirmation"
        self.handover_pub.publish(handover)
        cargo = CargoState()
        cargo.stamp = stamp
        cargo.robot_id = handover.robot_id
        cargo.job_id = handover.job_id
        cargo.state = cargo_state_for_confirmation(confirmed)
        cargo.sensor_confirmed = confirmed
        cargo.detail = handover.detail
        self.cargo_pub.publish(cargo)


def main() -> None:
    rclpy.init()
    node = GazeboOmxAdapter()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
