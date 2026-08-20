#!/usr/bin/env python3
"""Gazebo 세계와 SLAM 지도가 같은 자리에 있는지 라이다로 검증한다.

## 왜 필요한가

지도는 두 가지 일을 한다. 하나는 **보여 주는 것**이고 하나는 **위치를 정하는
것**이다. 예쁜 `.glb` 를 Gazebo 에 올려도 그 벽이 `new_map_2.pgm` 의 벽과 다른
자리에 있으면, AMCL 은 라이다가 보는 벽과 지도의 벽을 맞추려다 로봇 자세를
그만큼 밀어 버린다. 그러면 "도착했다"고 말하는 자리가 원장이 아는 자리와 어긋난다.

이 검사는 그 어긋남을 **숫자로** 준다. 지금 자세에서 지도를 향해 광선을 쏴서
얻은 거리와, 시뮬레이터의 라이다가 실제로 잰 거리를 빔마다 견준다.

    두 값이 같다  -> 세계와 지도가 정합돼 있다
    두 값이 다르다 -> 그 차이가 곧 주행이 틀어질 거리다

## 쓰는 법

    source install/setup.bash
    python3 scripts/p0_check_world_alignment.py                 # 기본 pinky_01
    python3 scripts/p0_check_world_alignment.py --robot pinky_02 --samples 20

로봇을 여러 자리로 옮겨 가며 돌려야 한다. 한 자리에서 맞는 것은 우연일 수 있지만,
서로 다른 세 자리에서 맞으면 회전·평행이동이 모두 맞았다는 뜻이다.
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys
from pathlib import Path

import rclpy
import yaml
from PIL import Image
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer, TransformListener

ROOT = Path(__file__).resolve().parents[1]
MAPS = ROOT / "control_ui" / "rmf_control_ui" / "data" / "rmf_maps"


class Grid:
    """점유 격자에 광선을 쏜다."""

    def __init__(self, map_yaml: Path) -> None:
        meta = yaml.safe_load(map_yaml.read_text(encoding="utf-8"))
        image = Image.open(map_yaml.parent / meta["image"]).convert("L")
        self.width, self.height = image.size
        self.pixels = list(image.getdata())
        self.resolution = float(meta["resolution"])
        self.origin_x, self.origin_y = (float(v) for v in meta["origin"][:2])
        self.name = map_yaml.stem

    def occupied(self, x: float, y: float) -> bool:
        c = int((x - self.origin_x) / self.resolution)
        r = self.height - 1 - int((y - self.origin_y) / self.resolution)
        if not (0 <= r < self.height and 0 <= c < self.width):
            return True                      # 지도 밖은 벽으로 친다
        return self.pixels[r * self.width + c] <= 200

    def cast(self, x: float, y: float, angle: float, limit: float) -> float | None:
        """(x, y) 에서 angle 방향으로 벽에 닿을 때까지 간 거리. 못 닿으면 None."""
        step = self.resolution / 2.0
        distance = 0.0
        dx, dy = math.cos(angle) * step, math.sin(angle) * step
        cx, cy = x, y
        while distance < limit:
            cx += dx
            cy += dy
            distance += step
            if self.occupied(cx, cy):
                return distance
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robot", default="pinky_01")
    parser.add_argument("--map", type=Path, default=None, help="지도 yaml. 생략하면 .trihouse/map_yaml")
    parser.add_argument("--samples", type=int, default=12, help="검사할 스캔 수")
    parser.add_argument("--tolerance", type=float, default=0.05, help="맞다고 볼 오차 (m)")
    args = parser.parse_args()

    map_yaml = args.map
    if map_yaml is None:
        recorded = ROOT / ".trihouse" / "map_yaml"
        if not recorded.is_file():
            print("[실패] .trihouse/map_yaml 이 없습니다. --map 으로 지도를 주세요.")
            return 1
        map_yaml = Path(recorded.read_text().strip())
    grid = Grid(map_yaml)
    print(f"지도 {grid.name}  {grid.width}x{grid.height} @ {grid.resolution} m")

    rclpy.init()
    node = Node("p0_check_world_alignment")
    buffer = Buffer()
    TransformListener(buffer, node)
    scans: list[LaserScan] = []
    node.create_subscription(
        LaserScan, f"/{args.robot}/scan", scans.append,
        QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT),
    )

    lidar_frame = f"{args.robot}/rplidar_link"
    errors: list[float] = []
    agreed = compared = used = 0
    deadline = node.get_clock().now().nanoseconds + 30 * 10 ** 9
    while rclpy.ok() and used < args.samples and node.get_clock().now().nanoseconds < deadline:
        rclpy.spin_once(node, timeout_sec=0.2)
        if not scans:
            continue
        scan = scans.pop()
        scans.clear()
        try:
            tf = buffer.lookup_transform("map", lidar_frame, rclpy.time.Time())
        except Exception:
            continue
        t = tf.transform.translation
        q = tf.transform.rotation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        used += 1
        for index, measured in enumerate(scan.ranges):
            if not math.isfinite(measured) or measured <= scan.range_min:
                continue
            if measured >= scan.range_max - 1e-3:
                continue                      # 아무것도 못 본 빔은 견줄 것이 없다
            angle = yaw + scan.angle_min + index * scan.angle_increment
            predicted = grid.cast(t.x, t.y, angle, scan.range_max)
            if predicted is None:
                continue
            compared += 1
            error = abs(predicted - measured)
            errors.append(error)
            agreed += error <= args.tolerance

    node.destroy_node()
    rclpy.shutdown()

    if not errors:
        print("[실패] 견줄 빔이 없습니다. 시뮬레이터가 떠 있고 AMCL 이 map->odom 을 내보내는지,")
        print(f"       그리고 /{args.robot}/scan 이 오는지 확인하세요.")
        print("       Gazebo 세계에 벽이 하나도 없으면 라이다가 아무것도 못 봅니다 — 그것도 이 결과가 됩니다.")
        return 1

    errors.sort()
    print(f"\n스캔 {used}개, 빔 {compared}개 비교")
    print(f"  중앙값 오차 {statistics.median(errors):.3f} m")
    print(f"  90 백분위  {errors[int(0.9 * (len(errors) - 1))]:.3f} m")
    print(f"  최대       {errors[-1]:.3f} m")
    share = agreed / compared
    print(f"  {args.tolerance:.2f} m 안에 든 빔 {share * 100:.1f} %")
    print()
    if share >= 0.90:
        print("정합됨. 지도의 벽과 세계의 벽이 같은 자리에 있습니다.")
        return 0
    if share >= 0.60:
        print("어긋남. 회전은 대체로 맞고 평행이동이 남은 모양입니다 — world 의 <pose> x y 를 조정하세요.")
        return 2
    print("크게 어긋남. 회전(yaw) 또는 축척부터 확인하세요. .glb 단위가 mm 이면 0.001 배가 필요합니다.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
