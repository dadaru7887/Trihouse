#!/usr/bin/env python3
"""라이다 스캔을 방향별로 갈라 찍는다. 무엇이 어느 쪽에 있는지 알기 위해서다.

`safety_supervisor` 가 내는 `scan_nearby` 는 360° 최솟값이라 "가깝다" 만 말해
준다. 사람이 물체를 찾으려면 방향이 필요하다.

    scripts/ops_scan_sectors.py --namespace pinky_01

읽는 법. 좁은 각도 구간에 여러 빔이 **같은 거리**로 걸리고 **좌우가 크게
비대칭**이면 벽이 아니라 로봇에 붙었거나 옆에 놓인 물체다. 2026-08-24 20:10 에
왼쪽 39.8 cm 대 오른쪽 13.3 cm 였고, -45°~-49° 구간이 전부 13.3 cm 였다.

스캔이 한 건도 오지 않으면 라이다 USB 를 의심한다. 프로세스가 살아 있어도
장치가 빠져 있으면 토픽이 조용하다.

    ssh pinky@192.168.0.21 'lsusb | grep -v "root hub"'
    ssh pinky@192.168.0.21 'ls /dev/ttyUSB*'
"""

from __future__ import annotations

import argparse
import math
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan


# 라이다가 로봇 정면에 대해 얼마나 돌아 달려 있는가. `pinky.urdf.xacro` 의
# `rplidar_link_fixed_joint` 가 `rpy="0 0 ${pi}"` 다 — 스캔각 0 이 로봇 뒤를
# 가리킨다. 이 보정 없이 각도를 읽으면 정확히 반대쪽을 가리키게 된다.
SCAN_FORWARD_OFFSET_RAD = math.pi

SECTORS = (
    (-30, 30, "정면"),
    (30, 90, "좌"),
    (-90, -30, "우"),
    (90, 150, "좌후"),
    (-150, -90, "우후"),
)


def _sector_of(degrees: float) -> str:
    for low, high, label in SECTORS:
        if low <= degrees < high:
            return label
    return "뒤"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="pinky_01")
    parser.add_argument("--timeout-s", type=float, default=15.0)
    parser.add_argument("--top", type=int, default=8)
    args = parser.parse_args()

    rclpy.init()
    node = Node("ops_scan_sectors")
    received: dict[str, LaserScan] = {}
    node.create_subscription(
        LaserScan,
        f"/{args.namespace}/scan",
        lambda message: received.setdefault("scan", message),
        qos_profile_sensor_data,
    )

    deadline = time.monotonic() + args.timeout_s
    while time.monotonic() < deadline and "scan" not in received:
        rclpy.spin_once(node, timeout_sec=0.2)

    scan = received.get("scan")
    node.destroy_node()
    rclpy.shutdown()

    if scan is None:
        print(
            f"/{args.namespace}/scan 을 한 건도 받지 못했습니다.\n"
            "라이다 USB 를 확인하세요 — 프로세스가 살아 있어도 장치가 빠지면 조용합니다.\n"
            "  ssh pinky@192.168.0.21 'lsusb | grep -v \"root hub\"'\n"
            "  ssh pinky@192.168.0.21 'ls /dev/ttyUSB*'",
            file=sys.stderr,
        )
        return 1

    points: list[tuple[float, float]] = []
    for index, value in enumerate(scan.ranges):
        if not math.isfinite(value) or value < scan.range_min or value > scan.range_max:
            continue
        angle = (
            scan.angle_min
            + index * scan.angle_increment
            + SCAN_FORWARD_OFFSET_RAD
        )
        angle = (angle + math.pi) % (2 * math.pi) - math.pi
        points.append((value, math.degrees(angle)))

    if not points:
        print("유효한 빔이 없습니다. 라이다가 회전하고 있는지 확인하세요.", file=sys.stderr)
        return 1

    points.sort()
    print(f"유효 빔 {len(points)} / 전체 {len(scan.ranges)}")
    print()
    print(f"가장 가까운 {args.top}개  (0=정면, +=좌, -=우, 180=뒤)")
    for value, degrees in points[: args.top]:
        print(f"   {value * 100:6.1f} cm  {degrees:+7.1f} deg   {_sector_of(degrees)}")

    print()
    print("구간별 최근접")
    nearest: dict[str, float] = {}
    for value, degrees in points:
        label = _sector_of(degrees)
        if label not in nearest or value < nearest[label]:
            nearest[label] = value
    for _, _, label in SECTORS:
        text = f"{nearest[label] * 100:6.1f} cm" if label in nearest else "   없음"
        print(f"   {label:<4} {text}")
    if "뒤" in nearest:
        print(f"   뒤   {nearest['뒤'] * 100:6.1f} cm")

    # 좌우 비대칭은 "환경이 아니라 물체" 의 신호다. 사람이 매번 암산하지 않도록
    # 여기서 판정까지 해 둔다.
    left, right = nearest.get("좌"), nearest.get("우")
    print()
    closest = points[0][0]
    if closest >= 0.20:
        print(f"판정: 출발 가능 (최근접 {closest * 100:.1f} cm)")
    elif closest >= 0.15:
        print(f"판정: 여유 부족 (최근접 {closest * 100:.1f} cm) — 눈으로 확인 권장")
    else:
        print(f"판정: 출발 불가 (최근접 {closest * 100:.1f} cm)")
        print("      로봇 몸통(뒤 0.16 m) 안쪽이면 충전 케이블이나 물건이다.")
    if left is not None and right is not None:
        ratio = max(left, right) / max(min(left, right), 1e-6)
        if ratio >= 2.0:
            near_side = "우" if right < left else "좌"
            print(
                f"      좌우 비대칭 {left * 100:.1f} cm vs {right * 100:.1f} cm "
                f"— {near_side}측을 확인하세요."
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
