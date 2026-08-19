"""Gazebo 데모용 OMX 상태 adapter.

실기 OMX endpoint를 추측하지 않는다. 이 node는 공용 HandoverState/CargoState만 발행하며,
`mock_load_confirmed` parameter로 시연자가 적재 물리 확인을 명시적으로 켤 수 있다.

P0에서는 `OmxProtocolSimulator`가 같은 프로세스에서 Gateway 명령 계약을
검증하고 결정적 상태 전이를 만든다. 실제 OMX motion은 나가지 않는다.

## 주행 로봇 도착에 반응한다

`auto_load_on_handover_ready` 가 참이면, 짝지어진 Pinky 가
`HandoverState.STATE_READY` 를 내는 것을 보고 적재를 시작한 것처럼 굴어
`load_delay_s` 뒤에 `CargoState.STATE_LOCKED + sensor_confirmed` 로 넘어간다.

**이것은 시뮬레이션 대역이다.** Gazebo 에는 화물 잠금도 로드셀도 없어서 물리
확인을 만들어 낼 방법이 없다. 실물에서는 이 노드를 실제 센서를 읽는 노드로
교체한다 — 같은 `CargoState` 를 내보내면 위층은 그대로 돈다. 교체를 잊은 채
실물로 넘어가면 **빈 로봇이 실렸다고 기록된다.** 그래서 기본값은 꺼짐이고
bringup 이 시뮬에서만 명시적으로 켠다.
"""

import rclpy
from rclpy.node import Node
from trihouse_interfaces.msg import CargoState, HandoverState

from .protocol_simulator import OmxProtocolSimulator


# 인계 대기 신호를 받은 뒤 적재 확인까지 두는 시간. 즉시 확정하면 로봇이 아직
# 도착 보고를 원장에 올리기도 전에 적재가 났다고 적혀, 순서가 뒤집힌 기록이 남는다.
DEFAULT_LOAD_DELAY_S = 2.0


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
        # 짝지어진 Pinky 가 인계 대기를 알리면 스스로 적재 확인을 만든다(시뮬 전용).
        self.declare_parameter("auto_load_on_handover_ready", False)
        self.declare_parameter("load_delay_s", DEFAULT_LOAD_DELAY_S)
        self._auto_confirmed = False
        self._load_at: float | None = None
        # 시뮬레이터는 이 adapter가 대표하는 OMX 하나만 응답한다.
        self.simulator = OmxProtocolSimulator(
            omx_id=str(self.get_parameter("omx_id").value)
        )
        self.handover_pub = self.create_publisher(HandoverState, "/trihouse/handover/state", 10)
        self.cargo_pub = self.create_publisher(CargoState, "trihouse/cargo/state", 10)
        # 같은 토픽으로 Pinky 도 자기 상태를 낸다. robot_id 로 자기 짝만 본다.
        self.create_subscription(
            HandoverState, "/trihouse/handover/state", self._on_handover, 10
        )
        self.create_timer(0.5, self._publish)

    def _on_handover(self, message: HandoverState) -> None:
        """짝지어진 Pinky 의 인계 대기 신호에만 반응한다."""
        if not bool(self.get_parameter("auto_load_on_handover_ready").value):
            return
        if message.robot_id != str(self.get_parameter("robot_id").value):
            return
        # 같은 토픽에 자기 상태도 낸다. 자기 발행을 되먹으면 안 된다.
        if message.actor_id == str(self.get_parameter("omx_id").value):
            return
        if message.state == HandoverState.STATE_READY and self._load_at is None:
            self._load_at = self._now_s() + float(self.get_parameter("load_delay_s").value)
            self.get_logger().info(
                f"[{self.get_parameter('omx_id').value}] "
                f"{message.robot_id} 도착 확인 — 적재를 시작합니다."
            )
        elif message.state in (HandoverState.STATE_IDLE, HandoverState.STATE_CONFIRMED):
            self._load_at = None
            self._auto_confirmed = False

    def _now_s(self) -> float:
        return self.get_clock().now().nanoseconds / 1e9

    def _publish(self) -> None:
        if self._load_at is not None and not self._auto_confirmed:
            if self._now_s() >= self._load_at:
                self._auto_confirmed = True
                self.get_logger().info(
                    f"[{self.get_parameter('omx_id').value}] 적재 완료 — cargo lock 확인."
                )
        confirmed = (
            bool(self.get_parameter("mock_load_confirmed").value) or self._auto_confirmed
        )
        stamp = self.get_clock().now().to_msg()
        handover = HandoverState()
        handover.stamp = stamp
        handover.robot_id = str(self.get_parameter("robot_id").value)
        handover.job_id = str(self.get_parameter("job_id").value)
        handover.job_step_id = str(self.get_parameter("job_step_id").value)
        handover.station_id = str(self.get_parameter("station_id").value)
        handover.actor_id = str(self.get_parameter("omx_id").value)
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
