"""관제 좌표계(unit, y↓)와 Gazebo 월드 좌표계(m, y↑) 변환.

관제센터 `WarehouseLayout`는 폭 120 × 높이 72 unit의 화면 좌표계를 쓴다
(원점 좌상단, y가 아래로 증가). Gazebo 월드는 창고 중심이 원점인 미터
단위 우수 좌표계다.

    x_m = (x_u - width/2)  * scale
    y_m = (height/2 - y_u) * scale
    yaw = -heading_u                     # y축이 뒤집히므로 회전 방향도 반대
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class WarehouseFrame:
    scale: float = 0.1  # m / unit
    width: float = 120.0
    height: float = 72.0

    # ── 관제 → 월드
    def to_world(self, x_u: float, y_u: float) -> tuple[float, float]:
        return (
            (x_u - self.width / 2) * self.scale,
            (self.height / 2 - y_u) * self.scale,
        )

    def yaw_of(self, heading_u: float) -> float:
        return -heading_u

    # ── 월드 → 관제
    def to_units(self, x_m: float, y_m: float) -> tuple[float, float]:
        return (
            x_m / self.scale + self.width / 2,
            self.height / 2 - y_m / self.scale,
        )

    def heading_of(self, yaw: float) -> float:
        return -yaw

    def length_to_world(self, units: float) -> float:
        return units * self.scale

    def length_to_units(self, meters: float) -> float:
        return meters / self.scale

    def zone_of(self, x_u: float) -> str:
        """3온도 구획. layout.dart `zoneOfX`와 동일한 경계."""
        if x_u < 50:
            return "ambient"
        if x_u < 88:
            return "chilled"
        return "frozen"


def yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def compose(
    base: tuple[float, float, float], local: tuple[float, float, float]
) -> tuple[float, float, float]:
    """스폰 포즈(월드) ⊕ 오도메트리(스폰 기준) = 월드 포즈.

    Gazebo DiffDrive 플러그인의 odom은 스폰 지점을 원점으로 하므로,
    월드 포즈를 얻으려면 스폰 포즈를 앞에 합성해야 한다.
    """
    bx, by, byaw = base
    lx, ly, lyaw = local
    c, s = math.cos(byaw), math.sin(byaw)
    return (bx + c * lx - s * ly, by + s * lx + c * ly, wrap(byaw + lyaw))


def wrap(angle: float) -> float:
    """각도를 (-π, π]로 정규화."""
    return math.atan2(math.sin(angle), math.cos(angle))
