#!/usr/bin/env python3
"""손으로 옮겨 놓은 Pinky 의 AMCL 을 대략 위치로 다시 수렴시킨다.

로봇을 들어 옮기면 odometry 가 끊긴다. AMCL 은 그 사실을 알 방법이 없어 옮기기
전 좌표를 계속 보고하고, 그 값을 그대로 설정에 넣으면 실측이 아니라 옛 좌표를
베껴 쓰는 것이 된다.

    scripts/ops_seed_amcl.py --namespace pinky_01 --x 1.05 --y 0.80 --yaw-deg 19.2

대략값을 주면 AMCL 이 스캔으로 다듬는다. 이 도구는 씨앗을 뿌리고 수렴을
지켜본 다음, 자리가 잡히면 실측값을 찍는다. 씨앗값 자체를 설정에 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy

from geometry_msgs.msg import PoseWithCovarianceStamped
from trihouse_interfaces.msg import RobotStatus


def _yaw_from_quaternion(q) -> float:
    return math.atan2(
        2.0 * (q.w * q.z + q.x * q.y),
        1.0 - 2.0 * (q.y * q.y + q.z * q.z),
    )


class Seeder(Node):
    def __init__(self, namespace: str) -> None:
        super().__init__("ops_seed_amcl")
        self._namespace = namespace
        # AMCL 의 initialpose 구독은 RViz 와 같은 기본 QoS 다.
        self._pub = self.create_publisher(
            PoseWithCovarianceStamped, f"/{namespace}/initialpose", 10
        )
        status_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.VOLATILE,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self.latest: tuple[float, float, float] | None = None
        self.create_subscription(
            RobotStatus, f"/{namespace}/trihouse/status", self._on_status, status_qos
        )

    def _on_status(self, message: RobotStatus) -> None:
        if message.frame_id != "map":
            return
        pose = message.pose.pose
        self.latest = (
            pose.position.x,
            pose.position.y,
            _yaw_from_quaternion(pose.orientation),
        )

    def seed(self, x: float, y: float, yaw: float, spread_m: float, spread_rad: float) -> None:
        message = PoseWithCovarianceStamped()
        message.header.frame_id = "map"
        message.header.stamp = self.get_clock().now().to_msg()
        message.pose.pose.position.x = x
        message.pose.pose.position.y = y
        message.pose.pose.orientation.z = math.sin(yaw / 2.0)
        message.pose.pose.orientation.w = math.cos(yaw / 2.0)
        # 대각 성분만 채운다. 손으로 놓은 자리의 불확실성이므로 x·y·yaw 가 서로
        # 독립이라고 보는 것이 실제에 가깝다.
        covariance = [0.0] * 36
        covariance[0] = spread_m ** 2
        covariance[7] = spread_m ** 2
        covariance[35] = spread_rad ** 2
        message.pose.covariance = covariance
        self._pub.publish(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="pinky_01")
    parser.add_argument("--x", type=float, required=True)
    parser.add_argument("--y", type=float, required=True)
    parser.add_argument("--yaw-deg", type=float, required=True)
    parser.add_argument("--spread-m", type=float, default=0.10)
    parser.add_argument("--spread-deg", type=float, default=15.0)
    parser.add_argument("--settle-s", type=float, default=12.0)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--label", default="entry")
    args = parser.parse_args()

    yaw = math.radians(args.yaw_deg)

    rclpy.init()
    node = Seeder(args.namespace)

    # 구독자가 붙기 전에 publish 하면 AMCL 이 못 받는다. 조용히 실패하는 대신
    # 연결을 기다린다.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and node._pub.get_subscription_count() == 0:
        rclpy.spin_once(node, timeout_sec=0.2)
    subscribers = node._pub.get_subscription_count()
    node.get_logger().info(f"initialpose 구독자 = {subscribers}")
    if subscribers == 0:
        node.get_logger().error(
            f"/{args.namespace}/initialpose 를 듣는 노드가 없습니다. amcl 이 살아 있는지 확인하세요."
        )
        node.destroy_node()
        rclpy.shutdown()
        return 1

    node.seed(args.x, args.y, yaw, args.spread_m, math.radians(args.spread_deg))
    node.get_logger().info(
        f"씨앗 pose 발행: ({args.x:.4f}, {args.y:.4f}, {args.yaw_deg:.1f} deg)"
    )

    # 수렴을 기다린다. 이 사이 사람이 로봇을 조금 돌려 주면 훨씬 빨리 잡힌다.
    deadline = time.monotonic() + args.settle_s
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.2)

    collected: list[tuple[float, float, float]] = []
    deadline = time.monotonic() + 20.0
    while len(collected) < args.samples and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.2)
        if node.latest is not None:
            collected.append(node.latest)
            node.latest = None

    node.destroy_node()
    rclpy.shutdown()

    if not collected:
        print("수렴 후 status 를 받지 못했습니다.", file=sys.stderr)
        return 1

    xs = [value[0] for value in collected]
    ys = [value[1] for value in collected]
    sin_mean = statistics.fmean(math.sin(value[2]) for value in collected)
    cos_mean = statistics.fmean(math.cos(value[2]) for value in collected)
    x, y = statistics.median(xs), statistics.median(ys)
    settled_yaw = math.atan2(sin_mean, cos_mean)

    print(f"# 표본 {len(collected)} 건")
    print(f"#   x 산포 {max(xs) - min(xs):.4f} m, y 산포 {max(ys) - min(ys):.4f} m")
    print(f"#   씨앗 대비 이동 {math.hypot(x - args.x, y - args.y):.4f} m, "
          f"yaw {math.degrees(settled_yaw) - args.yaw_deg:+.2f} deg")
    print()
    print(f"    {args.label}: {{ x: {x!r}, y: {y!r}, yaw: {settled_yaw!r} }}")
    if args.label == "entry":
        print(
            f"    entry_zone:\n"
            f"      {{ x: {x!r}, y: {y!r}, yaw: {settled_yaw!r}, length: 0.05, width: 0.20 }}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
