#!/usr/bin/env python3
"""namespace 안의 TF 를 전역 `/tf` 로 흘려보낸다. 관측 도구를 붙이기 위한 것이다.

    python3 scripts/tf_relay.py pinky_01

왜 필요한가. nav2 노드는 `__ns:=/pinky_01` 과 `-r /tf:=tf` 로 뜬다. 로봇 두 대가
`/map` 과 `/amcl_pose` 를 공유하지 않게 하려고 일부러 격리한 것이다. 그 대가로
TF 가 `/pinky_01/tf` 에 있고, 전역 `/tf` 에는 `map -> odom` 이 없다. RViz 는
tf2 규약대로 절대 이름 `/tf` 를 보므로 "Frame [map] does not exist" 가 된다.

CLI remap(`-r /tf:=/pinky_01/tf`)이 먹으면 그것이 더 가볍다. 이 relay 는 그것이
먹지 않을 때 쓰는 확실한 경로다. **시뮬을 관측할 때만 쓴다** — 로봇을 두 대로
띄운 상태에서 두 relay 를 함께 돌리면 전역 `/tf` 에 두 로봇의 변환이 섞여
tf2 가 같은 프레임 이름을 두 번 보게 된다.

static TF 는 latch 된다. 양쪽 모두 transient_local 로 두지 않으면 늦게 붙은
구독자가 아무것도 받지 못한다.
"""
from __future__ import annotations

import sys

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from tf2_msgs.msg import TFMessage


def latched_qos(depth: int = 100) -> QoSProfile:
    qos = QoSProfile(depth=depth)
    qos.durability = QoSDurabilityPolicy.TRANSIENT_LOCAL
    qos.reliability = QoSReliabilityPolicy.RELIABLE
    return qos


class TfRelay(Node):
    def __init__(self, namespace: str) -> None:
        super().__init__("trihouse_tf_relay")
        source = f"/{namespace}/tf"
        source_static = f"/{namespace}/tf_static"

        self.dynamic_pub = self.create_publisher(TFMessage, "/tf", 100)
        self.static_pub = self.create_publisher(TFMessage, "/tf_static", latched_qos())

        self.create_subscription(TFMessage, source, self.dynamic_pub.publish, 100)
        self.create_subscription(
            TFMessage, source_static, self.static_pub.publish, latched_qos()
        )

        self.get_logger().info(f"relaying {source} -> /tf, {source_static} -> /tf_static")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    rclpy.init()
    node = TfRelay(sys.argv[1])
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
