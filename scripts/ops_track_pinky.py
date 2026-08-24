#!/usr/bin/env python3
"""운영 테스트 중 Pinky 한 대의 위치와 상태를 CSV 로 계속 남긴다.

`/<namespace>/trihouse/status` 하나만 구독한다. 그 토픽이 pose, battery, safety,
task_context, navigation_state 를 한 메시지로 싣고 있어서, 여러 토픽을 시간으로
맞춰 붙이는 것보다 기록이 어긋날 여지가 없다.

    scripts/ops_track_pinky.py --namespace pinky_01 \
      --output log/ops_test_2026-08-24/pk01_track.csv

각 행에는 지도에서 가장 가까운 waypoint 와 그 거리를 함께 적는다. 원시 좌표만
남기면 나중에 로그를 읽는 사람이 "지금 어디였나"를 매번 손으로 계산해야 한다.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy

from trihouse_interfaces.msg import RobotStatus


# new_map_2 published revision 의 waypoint. DB `locations` 가 정본이며 이 표는
# 로그를 사람이 읽을 수 있게 만드는 용도로만 쓴다.
WAYPOINTS = {
    "charging_station_01": (0.0570244747, 0.1949666005),
    "charging_station_02": (0.1336554086, -0.0065562838),
    "charging_station_narrow_exit": (0.7992961442, 0.0854053105),
    "ambient_storage_narrow_entry": (1.010244055594586, 0.916734497725354),
    "ambient_storage_loading_dock_01": (1.234, 0.743),
    "chilled_storage_narrow_entry": (1.101331522128124, -0.10045055614140724),
    "chilled_storage_loading_dock_01": (1.26, 0.193),
    "frozen_storage_narrow_entry": (1.1792881155, -1.1896842748),
    "frozen_storage_loading_dock_01": (1.3314581184, -0.8149269956),
    "packing_station_loading_dock_01": (0.351, -0.49),
    "packing_station_loading_dock_02": (0.351, -1.017),
    "safety_zone_01": (0.613, -1.249),
}

NAVIGATION_STATE = {
    0: "idle",
    1: "navigating",
    2: "arrived",
    3: "blocked",
    4: "failed",
}

SAFETY_STATE = {0: "clear", 1: "slow", 2: "stop", 3: "fault"}

FIELDS = [
    "wall_time",
    "stamp",
    "x",
    "y",
    "yaw_deg",
    "nearest_waypoint",
    "distance_m",
    "navigation_state",
    "safety_state",
    "safety_detail",
    "battery_pct",
    "ready",
    "dispatchable",
    "job_id",
    "job_step_id",
    "command_source",
    "task_progress",
    "errors",
]


def _yaw_from_quaternion(q) -> float:
    return math.atan2(
        2.0 * (q.w * q.z + q.x * q.y),
        1.0 - 2.0 * (q.y * q.y + q.z * q.z),
    )


def _nearest(x: float, y: float) -> tuple[str, float]:
    name, (wx, wy) = min(
        WAYPOINTS.items(),
        key=lambda item: math.hypot(x - item[1][0], y - item[1][1]),
    )
    return name, math.hypot(x - wx, y - wy)


class Tracker(Node):
    def __init__(self, namespace: str, output: Path, min_interval_s: float) -> None:
        super().__init__("ops_track_pinky")
        self._min_interval_s = min_interval_s
        self._last_written = 0.0

        output.parent.mkdir(parents=True, exist_ok=True)
        self._is_new = not output.exists() or output.stat().st_size == 0
        # 줄 단위로 흘려보낸다. 테스트가 중간에 끊겨도 그때까지의 궤적은 남는다.
        self._handle = output.open("a", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(self._handle, fieldnames=FIELDS)
        if self._is_new:
            self._writer.writeheader()
            self._handle.flush()

        # `status_node` 는 `create_publisher(RobotStatus, 'trihouse/status', 10)`
        # 으로 기본 QoS(RELIABLE/VOLATILE, depth 10)를 쓴다. 여기서 BEST_EFFORT 로
        # 구독하면 QoS 가 맞지 않아 한 건도 받지 못한 채 빈 CSV 만 남는다.
        qos = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.VOLATILE,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=10,
        )
        topic = f"/{namespace}/trihouse/status"
        self.create_subscription(RobotStatus, topic, self._on_status, qos)
        self.get_logger().info(f"구독: {topic} -> {output}")

    def _on_status(self, msg: RobotStatus) -> None:
        now = self.get_clock().now().nanoseconds / 1e9
        if now - self._last_written < self._min_interval_s:
            return
        self._last_written = now

        position = msg.pose.pose.position
        yaw = _yaw_from_quaternion(msg.pose.pose.orientation)
        nearest, distance = _nearest(position.x, position.y)

        row = {
            "wall_time": self._wall_time(),
            "stamp": f"{msg.stamp.sec}.{msg.stamp.nanosec:09d}",
            "x": f"{position.x:.4f}",
            "y": f"{position.y:.4f}",
            "yaw_deg": f"{math.degrees(yaw):.1f}",
            "nearest_waypoint": nearest,
            "distance_m": f"{distance:.3f}",
            "navigation_state": NAVIGATION_STATE.get(
                msg.navigation_state, str(msg.navigation_state)
            ),
            "safety_state": SAFETY_STATE.get(msg.safety.state, str(msg.safety.state)),
            "safety_detail": msg.safety.detail,
            "battery_pct": f"{msg.battery_percentage:.1f}",
            "ready": int(msg.ready),
            "dispatchable": int(msg.dispatchable),
            "job_id": msg.task_context.job_id,
            "job_step_id": msg.task_context.job_step_id,
            "command_source": msg.task_context.command_source,
            "task_progress": f"{msg.task_progress:.2f}",
            "errors": "|".join(msg.errors),
        }
        self._writer.writerow(row)
        self._handle.flush()

    @staticmethod
    def _wall_time() -> str:
        import datetime

        return datetime.datetime.now().isoformat(timespec="milliseconds")

    def destroy_node(self) -> bool:
        self._handle.close()
        return super().destroy_node()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="pinky_01")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--min-interval-s",
        type=float,
        default=0.5,
        help="같은 초에 여러 건이 와도 이 간격보다 촘촘히는 적지 않는다.",
    )
    args = parser.parse_args()

    rclpy.init()
    node = Tracker(args.namespace, args.output, args.min_interval_s)
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
