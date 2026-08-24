#!/usr/bin/env python3
"""손으로 놓아 둔 Pinky 의 현재 map pose 를 협로 설정에 붙여 넣을 형태로 찍는다.

`manual_placement_amcl` 방식의 실측 단계다. 사람이 로봇을 원하는 자리에 놓고
이것을 돌리면 `config/narrow_zones.<map>.yaml` 의 `entry` / `entry_zone` /
`dock_target` 에 그대로 넣을 수 있는 줄이 나온다.

    scripts/ops_read_pose.py --namespace pinky_01 --samples 20

여러 건을 모아 중앙값을 쓴다. AMCL 은 한 건마다 몇 mm 씩 흔들리므로 한 건만
읽으면 그 흔들림이 그대로 설정값이 되어 버린다.
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy

from trihouse_interfaces.msg import RobotStatus


def _yaw_from_quaternion(q) -> float:
    return math.atan2(
        2.0 * (q.w * q.z + q.x * q.y),
        1.0 - 2.0 * (q.y * q.y + q.z * q.z),
    )


class PoseReader(Node):
    def __init__(self, namespace: str, samples: int) -> None:
        super().__init__("ops_read_pose")
        self.samples: list[tuple[float, float, float]] = []
        self._wanted = samples
        self._frame_warned = False
        qos = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.VOLATILE,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self.create_subscription(
            RobotStatus, f"/{namespace}/trihouse/status", self._on_status, qos
        )

    @property
    def done(self) -> bool:
        return len(self.samples) >= self._wanted

    def _on_status(self, message: RobotStatus) -> None:
        # frame_id 가 map 이 아니면 그 pose 는 지도 좌표가 아니다. 그것을 설정에
        # 넣으면 로봇은 엉뚱한 자리를 목적지로 삼는다.
        if message.frame_id != "map":
            if not self._frame_warned:
                self.get_logger().warning(
                    f"frame_id={message.frame_id or '<empty>'} — map 이 아니어서 버린다"
                )
                self._frame_warned = True
            return
        pose = message.pose.pose
        self.samples.append(
            (pose.position.x, pose.position.y, _yaw_from_quaternion(pose.orientation))
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="pinky_01")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--timeout-s", type=float, default=30.0)
    parser.add_argument(
        "--label",
        default="entry",
        help="찍어 줄 키 이름. entry / dock_target / exit_target 중 하나.",
    )
    args = parser.parse_args()

    rclpy.init()
    node = PoseReader(args.namespace, args.samples)
    deadline = node.get_clock().now().nanoseconds / 1e9 + args.timeout_s
    while not node.done and node.get_clock().now().nanoseconds / 1e9 < deadline:
        rclpy.spin_once(node, timeout_sec=0.5)

    collected = list(node.samples)
    node.destroy_node()
    rclpy.shutdown()

    if not collected:
        print("status 를 한 건도 받지 못했습니다. bringup 과 DDS 환경을 확인하세요.", file=sys.stderr)
        return 1

    xs = [value[0] for value in collected]
    ys = [value[1] for value in collected]
    # yaw 는 ±pi 경계에서 산술 평균이 무너지므로 단위벡터로 평균한다.
    sin_mean = statistics.fmean(math.sin(value[2]) for value in collected)
    cos_mean = statistics.fmean(math.cos(value[2]) for value in collected)
    x, y = statistics.median(xs), statistics.median(ys)
    yaw = math.atan2(sin_mean, cos_mean)

    print(f"# 표본 {len(collected)} 건")
    print(f"#   x 산포 {max(xs) - min(xs):.4f} m, y 산포 {max(ys) - min(ys):.4f} m")
    print(f"#   yaw = {math.degrees(yaw):.2f} deg")
    print()
    print(f"    {args.label}: {{ x: {x!r}, y: {y!r}, yaw: {yaw!r} }}")
    if args.label == "entry":
        print(
            f"    entry_zone:\n"
            f"      {{ x: {x!r}, y: {y!r}, yaw: {yaw!r}, length: 0.05, width: 0.20 }}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
