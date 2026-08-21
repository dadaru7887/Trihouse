"""도크 앞 좁은 통로를 규칙 기반으로 지난다.

## 왜 Nav2 가 아닌가

통로 폭 0.20 m 에 로봇 필요 폭 0.14 m 라 편측 여유가 0.03 m 인데, AMCL 위치추정
오차는 0.08~0.11 m 다. **오차가 여유의 세 배다.** Nav2 는 절대 좌표로 계획하므로
구조적으로 지날 수 없고, 실제로 `compute_path_to_pose` 가 계속 abort 하면서 복구
동작(후진·회전)만 반복했다(2026-08-19 실측).

규칙 주행은 **진입점에서의 상대 이동**이라 AMCL 오차가 누적되지 않는다.

## 안전

속도 명령을 `cmd_vel` 에 직접 쏘지 않는다. Nav2 의 사슬 앞단인 `cmd_vel_nav` 로 넣어
가속 제한(velocity_smoother)과 충돌 감시(collision_monitor, LiDAR 로 1.2 초 앞 검사)를
그대로 통과시킨다. 원본 `narrow3_rule_based_docking.py` 는 `cmd_vel` 에 직접 쏘아
"반드시 사람이 옆에서 지켜보다가 Ctrl+C" 를 전제했다. 그 전제를 없앤다.

## 되먹임이 없다는 것

거리와 각도를 오도메트리·AMCL 로 재고, 시퀀스는 정해진 순서대로만 간다. 바퀴가
미끄러지면 그만큼 어긋나고 스스로 고치지 못한다. 그래서 **시퀀스가 끝난 뒤 도크
좌표와 대조**해 실제로 그 자리에 섰는지 확인한다(`verify_pose`). 이것이 "바구니가
로봇팔에 닿는 자리에 있는가" 를 판정하는 유일한 근거다.

이 층은 임시다. 마커 도킹이 붙으면 걷어낸다.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, hypot, sin
from typing import Any, Callable, Mapping, Sequence


# 스텝 종류.
ROTATE = "rotate"
STRAIGHT = "straight"
EXIT_ZONE = "exit_zone"
STEP_KINDS = (ROTATE, STRAIGHT, EXIT_ZONE)


class NarrowZoneError(RuntimeError):
    """규칙 주행을 시작하거나 이어 갈 수 없다."""


@dataclass(frozen=True)
class ZoneGeometry:
    """진입점과 그 자리를 인식할 직사각형.

    원이 아니라 직사각형인 이유는 통로가 좁고 길기 때문이다. 진행 방향으로 정렬해야
    실제 여유 공간과 맞는다. 병목처럼 방향과 무관한 원형 상호배제 구역과는 성격이 다르다.
    """

    x: float
    y: float
    yaw: float
    length: float
    width: float

    def contains(self, x: float, y: float) -> bool:
        """존 로컬 프레임으로 옮겨 직사각형 안인지 본다."""
        dx, dy = x - self.x, y - self.y
        c, s = cos(-self.yaw), sin(-self.yaw)
        along = dx * c - dy * s
        across = dx * s + dy * c
        return abs(along) <= self.length / 2 and abs(across) <= self.width / 2


@dataclass(frozen=True)
class NarrowZone:
    destination_code: str
    geometry: ZoneGeometry
    enter: tuple[tuple[str, float | None], ...]
    exit: tuple[tuple[str, float | None], ...]
    measured: Mapping[str, Any]
    # 있으면 Nav2가 entry에 도착한 뒤 고정 시퀀스 대신 /trihouse/dock action이
    # 해당 ArUco를 정렬하고 180도 회전·후진을 끝까지 소유한다.
    marker_id: str | None = None
    # 탈출 직후 Nav2 에 넘기기 전에 대조할 map 좌표. 특히 충전 베이는 시작점이
    # 벽에 가까워서 "존만 벗어남"으로는 충분하지 않다.
    exit_target: tuple[float, float, float] | None = None


def _step(raw: Sequence[Any], where: str) -> tuple[str, float | None]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise NarrowZoneError(f"{where}: 스텝은 [종류, 값] 두 항목이어야 한다 — {raw!r}")
    kind, value = str(raw[0]), raw[1]
    if kind not in STEP_KINDS:
        raise NarrowZoneError(f"{where}: 알 수 없는 스텝 종류 {kind!r}")
    if kind == EXIT_ZONE:
        return kind, None
    if not isinstance(value, (int, float)):
        raise NarrowZoneError(f"{where}: {kind} 는 숫자를 받는다 — {value!r}")
    return kind, float(value)


def load_zones(document: Mapping[str, Any], *, map_name: str) -> dict[str, NarrowZone]:
    """존 표를 읽는다. **지도가 다르면 거절한다.**

    값이 그 지도 좌표계에 묶여 있어서다. 다른 지도로 돌리면서 이 값을 쓰면 로봇이
    엉뚱한 자리에서 후진한다 — 조용히 통과시키면 안 되는 종류의 불일치다.
    """
    declared = str(document.get("map_name", ""))
    if declared != map_name:
        raise NarrowZoneError(
            f"존 표는 {declared!r} 지도의 값인데 지금 지도는 {map_name!r} 이다"
        )
    zones: dict[str, NarrowZone] = {}
    for code, body in (document.get("zones") or {}).items():
        if not bool(body.get("enabled", True)):
            continue
        entry, shape = body.get("entry") or {}, body.get("zone") or {}
        try:
            geometry = ZoneGeometry(
                x=float(entry["x"]), y=float(entry["y"]), yaw=float(entry["yaw"]),
                length=float(shape["length"]), width=float(shape["width"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise NarrowZoneError(f"{code}: entry/zone 값이 온전하지 않다") from error
        raw_exit_target = body.get("exit_target")
        if raw_exit_target is None:
            exit_target = None
        else:
            try:
                exit_target = (
                    float(raw_exit_target["x"]),
                    float(raw_exit_target["y"]),
                    float(raw_exit_target["yaw"]),
                )
            except (KeyError, TypeError, ValueError) as error:
                raise NarrowZoneError(f"{code}: exit_target 값이 온전하지 않다") from error
        zones[str(code)] = NarrowZone(
            destination_code=str(code),
            geometry=geometry,
            enter=tuple(_step(raw, f"{code}.enter") for raw in body.get("enter") or ()),
            exit=tuple(_step(raw, f"{code}.exit") for raw in body.get("exit") or ()),
            measured=dict(body.get("measured") or {}),
            marker_id=(
                str(body["marker_id"]) if body.get("marker_id") is not None else None
            ),
            exit_target=exit_target,
        )
    return zones


def normalize(angle: float) -> float:
    return atan2(sin(angle), cos(angle))


def verify_pose(
    current: tuple[float, float, float],
    target: tuple[float, float, float],
    *,
    xy_tolerance_m: float,
    yaw_tolerance_rad: float,
) -> tuple[bool, float, float]:
    """시퀀스가 끝난 자리가 도크인가.

    규칙 주행에는 되먹임이 없다. 바퀴가 미끄러지면 시퀀스는 "다 했다" 고 말하면서
    엉뚱한 자리에 서 있을 수 있다. **바구니가 로봇팔에 닿는 자리에 있는지**는 이
    대조로만 알 수 있다. 거리와 각도 차이를 함께 돌려주어 로그에 남긴다.
    """
    distance = hypot(current[0] - target[0], current[1] - target[1])
    yaw_error = abs(normalize(current[2] - target[2]))
    return (
        distance <= xy_tolerance_m and yaw_error <= yaw_tolerance_rad,
        distance,
        yaw_error,
    )


class NarrowZonePlan:
    """한 번의 진입 또는 탈출. 스텝을 하나씩 꺼내 주고 진행을 기억한다.

    실행(속도 발행, 대기)은 호출부가 한다. 이 클래스는 ROS 를 모른다 — 그래야 순서와
    중단 조건을 ROS 없이 시험할 수 있다.
    """

    def __init__(self, zone: NarrowZone, *, leaving: bool) -> None:
        self._zone = zone
        self._steps = list(zone.exit if leaving else zone.enter)
        self._index = 0
        self._leaving = leaving
        if not self._steps:
            raise NarrowZoneError(
                f"{zone.destination_code}: {'exit' if leaving else 'enter'} 시퀀스가 비어 있다"
            )

    @property
    def zone(self) -> NarrowZone:
        return self._zone

    @property
    def leaving(self) -> bool:
        return self._leaving

    @property
    def done(self) -> bool:
        return self._index >= len(self._steps)

    @property
    def progress(self) -> str:
        return f"{min(self._index + 1, len(self._steps))}/{len(self._steps)}"

    def next_step(self) -> tuple[str, float | None]:
        if self.done:
            raise NarrowZoneError("남은 스텝이 없다")
        step = self._steps[self._index]
        self._index += 1
        return step


def select_zone(
    zones: Mapping[str, NarrowZone], destination_code: str
) -> NarrowZone | None:
    """이 목적지가 협로 존인가. 아니면 지금까지처럼 Nav2 가 끝까지 간다."""
    return zones.get(destination_code)


def zone_containing(
    zones: Mapping[str, NarrowZone], x: float, y: float
) -> NarrowZone | None:
    """로봇이 지금 어느 존 안에 있는가.

    다음 이동 명령을 받았을 때 먼저 빠져나와야 하는지 판단한다. 이 경로가 없어서
    2026-08-19 에 로봇이 냉동창고에서 나오지 못했다.
    """
    for zone in zones.values():
        if zone.geometry.contains(x, y):
            return zone
    return None


def step_velocity(
    kind: str,
    value: float | None,
    current: tuple[float, float, float],
    started: tuple[float, float, float],
    *,
    max_linear: float,
    max_angular: float,
    yaw_tolerance: float,
    position_tolerance: float,
    zone: ZoneGeometry | None = None,
) -> tuple[float, float, bool] | None:
    """이 스텝의 속도 명령과 완료 여부. 완료면 `(0, 0, True)`.

    되돌려주는 속도는 `cmd_vel_nav` 로 나가 velocity_smoother 와 collision_monitor 를
    지난다. 여기서 가속을 다루지 않는 이유다.
    """
    if kind == ROTATE:
        error = normalize(float(value) - current[2])
        if abs(error) <= yaw_tolerance:
            return 0.0, 0.0, True
        return 0.0, max_angular if error > 0 else -max_angular, False
    if kind == STRAIGHT:
        travelled = hypot(current[0] - started[0], current[1] - started[1])
        remaining = abs(float(value)) - travelled
        if remaining <= position_tolerance:
            return 0.0, 0.0, True
        return (max_linear if float(value) >= 0 else -max_linear), 0.0, False
    if kind == EXIT_ZONE:
        if zone is None:
            raise NarrowZoneError("exit_zone 은 존 정보를 요구한다")
        if not zone.contains(current[0], current[1]):
            return 0.0, 0.0, True
        return max_linear, 0.0, False
    raise NarrowZoneError(f"알 수 없는 스텝 종류 {kind!r}")
