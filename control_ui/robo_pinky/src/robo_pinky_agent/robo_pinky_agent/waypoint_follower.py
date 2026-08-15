"""관제가 내려준 웨이포인트 열을 차동구동 명령으로 바꾸는 추종기.

Pinky는 제자리 회전이 가능한 차동구동이고 통로 폭이 좁으므로,
곡률 추종보다 "회전 정렬 → 직진"이 안정적이다.

  · 방위 오차가 `align_tol`보다 크면 제자리 회전
  · 그 밖에는 전진하면서 비례 제어로 방위 보정
  · 경유점은 `reach`, 종점은 `goal_reach` 안에 들어오면 소진

종점 반경이 따로 있는 이유: 관제가 주는 마지막 좌표는 랙 슬롯의 선반
중심선이라 로봇이 그 위에 올라설 수 없다. 현장 로봇도 통로에 서서 슬롯에
접근하므로, 종점만 넉넉한 반경으로 도착을 판정한다.
"""

from __future__ import annotations

import math

from .frames import wrap


class WaypointFollower:
    def __init__(
        self,
        reach: float = 0.12,
        goal_reach: float = 0.50,
        align_tol: float = 0.45,
        max_linear: float = 0.34,
        max_angular: float = 1.6,
        k_angular: float = 2.4,
        slow_radius: float = 0.25,
    ) -> None:
        self.reach = reach
        self.goal_reach = goal_reach
        self.align_tol = align_tol
        self.max_linear = max_linear
        self.max_angular = max_angular
        self.k_angular = k_angular
        self.slow_radius = slow_radius
        self._waypoints: list[tuple[float, float]] = []

    # ────────────────────────────────────────────────────────── 상태

    @property
    def remaining(self) -> int:
        return len(self._waypoints)

    @property
    def active(self) -> bool:
        return bool(self._waypoints)

    def set_path(
        self, waypoints: list[tuple[float, float]], goal_reach: float | None = None
    ) -> None:
        if goal_reach is not None:
            self.goal_reach = goal_reach
        self._waypoints = list(waypoints)

    def clear(self) -> None:
        self._waypoints.clear()

    # ────────────────────────────────────────────────────────── 제어

    def step(
        self, pose: tuple[float, float, float], speed_limit: float
    ) -> tuple[float, float]:
        """현재 월드 포즈(x, y, yaw)에서 (선속도, 각속도)를 계산한다."""
        x, y, yaw = pose
        self._consume(x, y)
        if not self._waypoints:
            return 0.0, 0.0

        tx, ty = self._waypoints[0]
        dx, dy = tx - x, ty - y
        dist = math.hypot(dx, dy)
        err = wrap(math.atan2(dy, dx) - yaw)

        v_cap = max(0.0, min(self.max_linear, speed_limit))
        w = max(-self.max_angular, min(self.max_angular, self.k_angular * err))

        if abs(err) > self.align_tol:
            return 0.0, w  # 제자리 회전으로 먼저 정렬

        v = v_cap
        if dist < self.slow_radius and len(self._waypoints) == 1:
            v = v_cap * max(0.25, dist / self.slow_radius)  # 종점 감속
        v *= max(0.35, 1.0 - abs(err) / self.align_tol * 0.65)  # 곡선 구간 감속
        return v, w

    def _consume(self, x: float, y: float) -> None:
        while self._waypoints:
            tx, ty = self._waypoints[0]
            reach = self.goal_reach if len(self._waypoints) == 1 else self.reach
            if math.hypot(tx - x, ty - y) > reach:
                return
            self._waypoints.pop(0)
