"""자동 bottleneck 접근 lease.

두 통로는 지름 0.2m, 실행 반경 0.1m로 고정되어 있고 운영자가 만든 대기
Waypoint가 없다. 로봇은 footprint가 반경 0.1m 구역에 닿기 전에 lease를
확인·획득하고, 통과가 끝나 footprint 전체와 여유가 구역을 벗어난 뒤에만
해제한다. 먼저 도착한 로봇이 이기며 `critical` 우선순위는 통과 순서를
바꾸지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from threading import RLock


BOTTLENECK_SOURCE_DIAMETER_M = 0.2
BOTTLENECK_EXECUTION_RADIUS_M = BOTTLENECK_SOURCE_DIAMETER_M / 2
DETOUR_WAIT_S = 15.0


@dataclass(frozen=True)
class BottleneckZone:
    """측정된 지름에서 파생된 통과 구역."""

    zone_id: str
    x: float
    y: float
    radius_m: float = BOTTLENECK_EXECUTION_RADIUS_M

    def __post_init__(self) -> None:
        if not self.zone_id.strip():
            raise ValueError("zone_id is required")
        if not all(math.isfinite(value) for value in (self.x, self.y)):
            raise ValueError("zone centre must be finite")
        if self.radius_m <= 0:
            raise ValueError("zone radius must be positive")


@dataclass(frozen=True)
class RobotFootprint:
    """접근 판정에 쓰는 로봇 외접 반경과 안전 여유."""

    radius_m: float
    safety_margin_m: float
    stopping_distance_m: float

    def __post_init__(self) -> None:
        values = (self.radius_m, self.safety_margin_m, self.stopping_distance_m)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("footprint values must be finite")
        if self.radius_m <= 0 or self.safety_margin_m < 0 or self.stopping_distance_m < 0:
            raise ValueError("footprint radius must be positive and margins non-negative")

    @property
    def approach_distance_m(self) -> float:
        """구역 경계까지 남은 거리 중 lease를 반드시 확보해야 하는 지점."""
        return self.radius_m + self.safety_margin_m + self.stopping_distance_m

    @property
    def clearance_distance_m(self) -> float:
        """footprint 전체와 여유가 구역 밖으로 나갔다고 볼 수 있는 거리."""
        return self.radius_m + self.safety_margin_m


@dataclass(frozen=True)
class LeaseDecision:
    acquired: bool
    holder: str = ""
    reason_code: str = ""
    detour_requested: bool = False
    detour_accepted: bool = False


@dataclass
class _Wait:
    since_s: float
    detour_requested_at_s: float | None = None


class BottleneckCoordinator:
    """등록된 구역에서만 동작하는 원자적 first-arrival lease."""

    def __init__(self, *, zones: tuple[BottleneckZone, ...]) -> None:
        if not zones:
            raise ValueError("at least one bottleneck zone is required")
        self._zones = {zone.zone_id: zone for zone in zones}
        if len(self._zones) != len(zones):
            raise ValueError("bottleneck zone IDs must be unique")
        self._lock = RLock()
        self._holders: dict[str, str] = {}
        self._held: set[tuple[str, str]] = set()
        self._waits: dict[tuple[str, str], _Wait] = {}

    # --- 접근 판정 ---------------------------------------------------------

    def must_acquire_before(
        self,
        zone_id: str,
        *,
        robot_x: float,
        robot_y: float,
        footprint: RobotFootprint,
    ) -> bool:
        """footprint가 구역을 침범하기 전에 lease가 필요한지 판단한다."""
        zone = self._zone(zone_id)
        gap = math.hypot(robot_x - zone.x, robot_y - zone.y) - zone.radius_m
        return gap <= footprint.approach_distance_m

    def waiting_waypoints(self) -> tuple[str, ...]:
        """P0는 수동 대기 Waypoint를 노출하지 않는다."""
        return ()

    # --- lease 획득/조회 ---------------------------------------------------

    def request(
        self,
        robot_name: str,
        zone_id: str,
        *,
        at_s: float,
        priority: str = "normal",
    ) -> LeaseDecision:
        if not robot_name.strip():
            raise ValueError("robot_name is required")
        zone = self._zone(zone_id)
        with self._lock:
            holder = self._holders.get(zone.zone_id, "")
            if holder == robot_name:
                self._waits.pop((robot_name, zone.zone_id), None)
                return LeaseDecision(True, holder=robot_name)
            if holder:
                # `critical`은 대기 Job 순서만 바꾸고 통과 순서는 바꾸지 않는다.
                self._waits.setdefault((robot_name, zone.zone_id), _Wait(at_s))
                return LeaseDecision(
                    False, holder=holder, reason_code="BOTTLENECK_OCCUPIED"
                )
            self._holders[zone.zone_id] = robot_name
            self._waits.pop((robot_name, zone.zone_id), None)
            return LeaseDecision(True, holder=robot_name)

    def poll(self, robot_name: str, zone_id: str, *, at_s: float) -> LeaseDecision:
        """대기 상태를 갱신하고 15초를 넘겼을 때만 우회 계산을 요청한다."""
        zone = self._zone(zone_id)
        with self._lock:
            holder = self._holders.get(zone.zone_id, "")
            if holder == robot_name:
                return LeaseDecision(True, holder=robot_name)
            wait = self._waits.get((robot_name, zone.zone_id))
            if wait is None:
                return self.request(robot_name, zone.zone_id, at_s=at_s)
            waited_from = (
                wait.detour_requested_at_s
                if wait.detour_requested_at_s is not None
                else wait.since_s
            )
            due = at_s - waited_from >= DETOUR_WAIT_S
            if due:
                wait.detour_requested_at_s = at_s
            return LeaseDecision(
                False,
                holder=holder,
                reason_code="BOTTLENECK_OCCUPIED",
                detour_requested=due,
            )

    def record_detour(
        self, robot_name: str, zone_id: str, *, valid: bool, at_s: float
    ) -> LeaseDecision:
        """Nav2가 점유 구역을 제외하고 계산한 경로의 사용 여부를 기록한다."""
        zone = self._zone(zone_id)
        with self._lock:
            key = (robot_name, zone.zone_id)
            if valid:
                self._waits.pop(key, None)
                return LeaseDecision(False, detour_accepted=True)
            wait = self._waits.get(key)
            if wait is not None:
                # 우회가 없으면 계속 기다린다. 다음 요청까지 다시 15초를 센다.
                wait.detour_requested_at_s = at_s
            return LeaseDecision(
                False,
                holder=self._holders.get(zone.zone_id, ""),
                reason_code="BOTTLENECK_OCCUPIED",
                detour_accepted=False,
            )

    def is_waiting(self, robot_name: str, zone_id: str) -> bool:
        with self._lock:
            return (robot_name, self._zone(zone_id).zone_id) in self._waits

    def holder(self, zone_id: str) -> str:
        with self._lock:
            return self._holders.get(self._zone(zone_id).zone_id, "")

    # --- 정지/비상 -------------------------------------------------------

    def hold(self, robot_name: str, zone_id: str, *, reason_code: str) -> LeaseDecision:
        """구역 안에서 정지하거나 비상 정지해도 lease를 유지한다."""
        zone = self._zone(zone_id)
        with self._lock:
            if self._holders.get(zone.zone_id) != robot_name:
                return LeaseDecision(False, holder=self._holders.get(zone.zone_id, ""))
            self._held.add((robot_name, zone.zone_id))
            return LeaseDecision(True, holder=robot_name, reason_code=reason_code)

    def resume(self, robot_name: str, zone_id: str) -> None:
        with self._lock:
            self._held.discard((robot_name, self._zone(zone_id).zone_id))

    # --- 해제 -------------------------------------------------------------

    def release(
        self,
        robot_name: str,
        zone_id: str,
        *,
        robot_x: float,
        robot_y: float,
        footprint: RobotFootprint,
    ) -> bool:
        """footprint 전체와 여유가 구역을 벗어났을 때만 해제한다."""
        zone = self._zone(zone_id)
        with self._lock:
            if self._holders.get(zone.zone_id) != robot_name:
                return False
            if (robot_name, zone.zone_id) in self._held:
                return False
            gap = math.hypot(robot_x - zone.x, robot_y - zone.y) - zone.radius_m
            if gap <= footprint.clearance_distance_m:
                return False
            del self._holders[zone.zone_id]
            self._waits.pop((robot_name, zone.zone_id), None)
            return True

    def _zone(self, zone_id: str) -> BottleneckZone:
        try:
            return self._zones[zone_id]
        except KeyError as error:
            raise KeyError(f"unknown bottleneck zone: {zone_id}") from error


__all__ = [
    "BOTTLENECK_EXECUTION_RADIUS_M",
    "BOTTLENECK_SOURCE_DIAMETER_M",
    "BottleneckCoordinator",
    "BottleneckZone",
    "DETOUR_WAIT_S",
    "LeaseDecision",
    "RobotFootprint",
]
