#!/usr/bin/env python3
"""배터리 정책을 `ready=True` 로 고정 발행해 배차 게이트를 연다.

**시험용 우회다. 정상 운영에서 쓰지 않는다.**

PK_01 의 SOC 판독이 한 주행 안에서 0.0~100.0 사이를 오간다(ADC 잡음). 로봇의
`battery_policy` 는 10% 이하를 `ready=False` 로 판정하므로 그 잡음이 그대로
`status.dispatchable` 을 5 초마다 껐다 켠다. fleet adapter 는 그때마다 로봇을
RMF 에서 빼고(`PINKY_NOT_READY`) 다시 넣어(`recommission`) 배차가 유지되지
못한다 — 주문이 `20=pending` 에서 영원히 멈추는 정체가 이것이다.

쓰는 순서는 이렇다. 로봇의 정책 노드를 먼저 내려야 한다. 둘이 같은 토픽에
발행하면 판정이 번갈아 뒤집혀 아무것도 나아지지 않는다.

    ssh pinky@192.168.0.21 'pgrep -f "trihouse_pinky_fleet/battery_policy"'
    ssh pinky@192.168.0.21 'kill -KILL <PID>'
    scripts/ops_battery_policy_override.py --namespace pinky_01 --robot-id PK_01

배터리 판독이 고쳐지면 이 도구를 멈추고 로봇의 정책 노드를 다시 띄운다.

    ros2 run trihouse_pinky_fleet battery_policy --ros-args -r __ns:=/pinky_01
"""

from __future__ import annotations

import argparse
import sys

import rclpy
from rclpy.node import Node

from trihouse_interfaces.msg import BatteryPolicyState


class Override(Node):
    def __init__(self, namespace: str, robot_id: str, rate_hz: float) -> None:
        super().__init__("ops_battery_policy_override")
        self._robot_id = robot_id
        # `status_node` 는 기본 QoS(depth 10)로 구독한다. 맞추지 않으면 연결되지
        # 않고, 그 실패는 "여전히 dispatchable=0" 으로만 보여 원인에서 멀다.
        self._publisher = self.create_publisher(
            BatteryPolicyState, f"/{namespace}/trihouse/battery/policy_state", 10
        )
        self.create_timer(1.0 / rate_hz, self._publish)
        self.get_logger().warning(
            f"시험용 우회: {namespace} 배터리 게이트를 ready=True 로 고정합니다."
        )

    def _publish(self) -> None:
        message = BatteryPolicyState()
        message.stamp = self.get_clock().now().to_msg()
        message.robot_id = self._robot_id
        message.state = BatteryPolicyState.STATE_NORMAL
        message.ready = True
        message.reason_code = "BATTERY_GATE_BYPASSED_FOR_OPS_TEST"
        message.detail = "2026-08-24 운영 테스트: SOC 판독 잡음으로 게이트를 우회함"
        self._publisher.publish(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="pinky_01")
    parser.add_argument("--robot-id", default="PK_01")
    parser.add_argument("--rate-hz", type=float, default=2.0)
    args = parser.parse_args()

    rclpy.init()
    node = Override(args.namespace, args.robot_id, args.rate_hz)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
