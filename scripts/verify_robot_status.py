#!/usr/bin/env python3
"""한 Pinky 의 status 가 RMF 에 받아들여질 상태인지 확인한다.

    python3 scripts/verify_robot_status.py pinky_01 [관측창_초]

`ros2 topic echo` 를 쓰지 않는다. 그 명령은 메시지 타입을 그래프에서 찾는데,
참가자가 많아지면 그래프 열거(`ros2 topic list`, `ros2 node list`)가 멈추는
호스트가 있다. 타입을 이미 손에 들고 직접 구독하면 그 문제를 지나간다.

발행자 수를 함께 센다. 이전 세대 노드가 남아 같은 토픽에 함께 발행하면 측정값이
그 자리에서 오염되므로, 1 이 아니면 나머지 숫자를 믿어서는 안 된다.

읽는 것은 세 가지다.

    frame_id      `map` 이어야 한다. RMF adapter 는 그 외의 값을 거절한다.
    dispatchable  false 면 adapter 가 로봇을 RMF 에 내보내지 않는다.
    errors        무엇이 위 둘을 막고 있는지 알려 준다.

종료코드는 frame_id 와 dispatchable 이 모두 만족될 때만 0 이다.
"""
import sys
import time

import rclpy
from rclpy.node import Node

from geometry_msgs.msg import PoseWithCovarianceStamped
from sensor_msgs.msg import LaserScan
from trihouse_interfaces.msg import RobotStatus


class Verifier(Node):
    def __init__(self, namespace: str) -> None:
        super().__init__("trihouse_status_verifier")
        self.status: RobotStatus | None = None
        self.amcl_pose: PoseWithCovarianceStamped | None = None
        self.scan_count = 0

        self.status_topic = f"/{namespace}/trihouse/status"
        self.scan_topic = f"/{namespace}/scan"
        self.amcl_topic = f"/{namespace}/amcl_pose"

        self.create_subscription(RobotStatus, self.status_topic, self._on_status, 10)
        self.create_subscription(LaserScan, self.scan_topic, self._on_scan, 10)
        self.create_subscription(
            PoseWithCovarianceStamped, self.amcl_topic, self._on_amcl, 10
        )

    def _on_status(self, message: RobotStatus) -> None:
        self.status = message

    def _on_scan(self, _message: LaserScan) -> None:
        self.scan_count += 1

    def _on_amcl(self, message: PoseWithCovarianceStamped) -> None:
        self.amcl_pose = message


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    namespace = sys.argv[1]
    window_s = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0

    rclpy.init()
    node = Verifier(namespace)
    # sim time 을 쓰는 노드에 붙어도 관측창은 벽시계로 재야 한다. 시뮬이 느리면
    # ROS 시계로 잰 창은 벽시계로 몇 배가 된다.
    deadline = time.monotonic() + window_s
    while rclpy.ok() and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.2)

    publishers = {
        "status": node.count_publishers(node.status_topic),
        "scan": node.count_publishers(node.scan_topic),
        "amcl_pose": node.count_publishers(node.amcl_topic),
    }

    print(f"--- {namespace} ({window_s:.0f}s wall) ---")
    print(f"publishers      : {publishers}")
    if any(count > 1 for count in publishers.values()):
        print(
            "  !! 발행자가 둘 이상이다. 이전 세대가 남아 있다는 뜻이고 아래 값은"
            " 믿을 수 없다. 시뮬을 완전히 내리고 다시 재라."
        )

    print(f"scan            : {node.scan_count} msgs ({node.scan_count / window_s:.2f} Hz wall)")

    if node.amcl_pose is None:
        # AMCL 은 `amcl_pose` 를 이벤트로만 낸다. 정지한 로봇에서는 비어 있는 것이
        # 정상이며, 위치추정 여부는 status 의 frame_id 로 판단한다.
        print("amcl_pose       : (없음 — 정지 상태에서는 정상)")
    else:
        position = node.amcl_pose.pose.pose.position
        print(f"amcl_pose       : x={position.x:.3f} y={position.y:.3f}")

    if node.status is None:
        print("status          : 없음  <- status_node 가 발행하지 않는다")
        print("RESULT: FAIL")
        node.destroy_node()
        rclpy.shutdown()
        return 1

    print(f"frame_id        : {node.status.frame_id}")
    print(f"dispatchable    : {node.status.dispatchable}")
    print(f"execution_ready : {node.status.execution_ready}")
    print(f"telemetry_valid : {node.status.telemetry_valid}")
    print(f"errors          : {list(node.status.errors)}")

    frame_ok = node.status.frame_id == "map"
    ok = frame_ok and node.status.dispatchable
    if not frame_ok:
        print("  frame_id 가 map 이 아니다 -> AMCL 이 위치추정 중인지 먼저 보라.")
    print(f"RESULT: {'PASS' if ok else 'FAIL'}")

    node.destroy_node()
    rclpy.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
