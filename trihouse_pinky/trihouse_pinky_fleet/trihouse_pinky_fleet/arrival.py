"""일반 Nav2 도착과 OMX 인수인계 정차의 pose 허용오차를 구분하는 함수."""
from __future__ import annotations

from math import atan2, cos, hypot, sin


def within_tolerance(*, current: tuple[float, float, float], target: tuple[float, float, float], xy_tolerance_m: float, yaw_tolerance_rad: float) -> bool:
    """-pi/pi 경계의 yaw 불연속 없이 평면 pose 오차를 비교한다."""
    x, y, yaw = current; target_x, target_y, target_yaw = target
    yaw_error = atan2(sin(yaw - target_yaw), cos(yaw - target_yaw))
    return hypot(x - target_x, y - target_y) <= xy_tolerance_m and abs(yaw_error) <= yaw_tolerance_rad
