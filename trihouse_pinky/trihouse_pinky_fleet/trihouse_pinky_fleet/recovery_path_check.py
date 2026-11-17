"""승인된 복구 좌표까지 가는 길을 지금 이 순간의 지도로 검사한다 (6C-Lite).

목적: `canonicalize_recovery_action` 은 좌표 값만 보고 지도를 보지 않는다. 그래서
"목적지 자체는 비어 있지만 가는 길에 기둥이 있다" 를 막지 못한다. 이 모듈이 그
자리를 채운다 — 출발점에서 목표까지를 n 개 지점으로 쪼개, 각 지점이 지금 비어
있고 발자국이 들어가며 출입금지 구역 밖인지 확인한다.

호출법: `fleet_node` 가 승인된 명령을 실행하기 **직전에** `rollout_blocked()` 를
부르고, 막혔으면 admission 에서 거부한다. 실행 직전에 부르는 이유는 이 검사가
"지금 이 순간의 정적 스냅샷" 만 보기 때문이다 — 미리 검사해 두면 그 사이에 사람이
걸어 들어온다.

원본: `upstream/dev_driving/02_pipeline_core/geometric_6c_lite.py`. 그쪽 docstring 이
스스로 밝혀 둔 한계를 여기에도 남긴다:

- 동적 장애물의 **미래 움직임을 예측하지 않는다.** 사람이 걸어오고 있어도 지금
  그 지점이 비어 있으면 통과시킨다. 그 위험은 실행 중 20 Hz safety supervisor 가
  맡는다.
- 로봇 자신의 위치 불확실성(localization drift, 바퀴 미끄러짐)을 모델링하지 않는다.
- 성공 **확률**을 내지 않는다. 이진 pass/fail 이다.
- 학습으로 개선되지 않는다. 규칙은 고정이다.

즉 이것은 학습된 world model rollout 이 아니라 그 자리에 놓은 기하학적 근사다.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol, Sequence


# 경로를 몇 개 지점으로 쪼갤지. 원본 기본값과 같다.
DEFAULT_STEPS = 8

# 스텝 간 최소 간격. costmap 해상도(0.03 m)보다 촘촘하면 같은 셀을 반복 조회할 뿐
# 새 정보가 없다.
MIN_STEP_SPACING_M = 0.05


class MapQueries(Protocol):
    """`costmap_view.CostmapView` 가 만족하는 최소 인터페이스."""

    @property
    def ready(self) -> bool: ...

    def costmap_free(self, x_m: float, y_m: float) -> bool: ...

    def footprint_fits(self, x_m: float, y_m: float, yaw_rad: float) -> bool: ...

    def keepout_violation(self, x_m: float, y_m: float) -> bool: ...


@dataclass(frozen=True)
class RolloutStep:
    """어느 지점에서 무엇 때문에 막혔는지 남기기 위한 진단 기록."""

    index: int
    x_m: float
    y_m: float
    yaw_rad: float
    fraction: float
    costmap_free: bool
    footprint_fits: bool
    keepout_violation: bool

    @property
    def passed(self) -> bool:
        return self.costmap_free and self.footprint_fits and not self.keepout_violation

    @property
    def reason(self) -> str:
        if not self.costmap_free:
            return "COSTMAP_OCCUPIED"
        if not self.footprint_fits:
            return "FOOTPRINT_BLOCKED"
        return "KEEP_OUT_ZONE"


@dataclass(frozen=True)
class RolloutReport:
    passed: bool
    detail: str
    steps: tuple[RolloutStep, ...]


def _shortest_angle(value: float) -> float:
    while value > math.pi:
        value -= 2.0 * math.pi
    while value < -math.pi:
        value += 2.0 * math.pi
    return value


def _interpolate(
    start: tuple[float, float, float],
    goal: tuple[float, float, float],
    steps: int,
) -> list[tuple[float, float, float, float]]:
    """출발점은 빼고 목표점은 포함한 `steps` 개 지점.

    직선 보간이라 Nav2 의 실제 경로 곡률은 반영하지 않는다 — 이 모듈의 한계 중
    하나다. 복구 이동은 0.25 m 이내라 직선 근사의 오차가 작다는 전제가 있다.
    """
    start_x, start_y, start_yaw = start
    goal_x, goal_y, goal_yaw = goal
    delta_yaw = _shortest_angle(goal_yaw - start_yaw)
    points = []
    for index in range(1, steps + 1):
        fraction = index / steps
        points.append((
            start_x + (goal_x - start_x) * fraction,
            start_y + (goal_y - start_y) * fraction,
            start_yaw + delta_yaw * fraction,
            fraction,
        ))
    return points


def rollout(
    start: tuple[float, float, float],
    goal: tuple[float, float, float],
    queries: MapQueries,
    *,
    steps: int = DEFAULT_STEPS,
) -> RolloutReport:
    """경로를 쪼개 검사하고 **첫 위반에서 즉시 멈춘다**.

    뒤 지점을 계속 확인해 봐야 판정은 이미 정해졌고, 막힌 지점 뒤의 좌표는 로봇이
    도달하지 못하므로 조회할 의미가 없다.
    """
    if not queries.ready:
        # 지도를 못 받았으면 "비어 있다" 고 말할 근거가 없다. fail-closed.
        return RolloutReport(False, "COSTMAP_UNAVAILABLE", ())
    distance = math.hypot(goal[0] - start[0], goal[1] - start[1])
    effective = steps
    if distance > 0.0 and distance / steps < MIN_STEP_SPACING_M:
        effective = max(1, int(distance / MIN_STEP_SPACING_M))
    checked: list[RolloutStep] = []
    for index, (x_m, y_m, yaw_rad, fraction) in enumerate(
        _interpolate(start, goal, effective)
    ):
        step = RolloutStep(
            index=index,
            x_m=x_m,
            y_m=y_m,
            yaw_rad=yaw_rad,
            fraction=fraction,
            costmap_free=queries.costmap_free(x_m, y_m),
            footprint_fits=queries.footprint_fits(x_m, y_m, yaw_rad),
            keepout_violation=queries.keepout_violation(x_m, y_m),
        )
        checked.append(step)
        if not step.passed:
            return RolloutReport(
                False,
                f"{step.reason}@{index + 1}/{effective}",
                tuple(checked),
            )
    return RolloutReport(True, f"CLEAR/{effective}", tuple(checked))


def rollout_blocked(
    start: tuple[float, float, float],
    goal: tuple[float, float, float],
    queries: MapQueries | None,
    *,
    steps: int = DEFAULT_STEPS,
) -> str | None:
    """막혔으면 사유 문자열, 통과하면 `None`.

    `queries` 가 없다는 것은 이 로봇에 지도 조회가 붙어 있지 않다는 뜻이고, 그때는
    검사를 건너뛰는 게 아니라 막는다. 검사가 없는 채로 자동 실행되면 안 된다.
    """
    if queries is None:
        return "COSTMAP_UNAVAILABLE"
    report = rollout(start, goal, queries, steps=steps)
    return None if report.passed else report.detail


def target_pose(
    robot_pose: tuple[float, float, float],
    coord: tuple[float, float, float],
    map_target: tuple[float, float, float] | None,
) -> tuple[float, float, float]:
    """검사할 목표 자세를 map 프레임으로 환산한다.

    REJOIN 만 절대 좌표를 들고 오고 나머지는 로봇 기준 상대 offset 이다. 둘을
    섞으면 상대값을 map 좌표로 조회하게 되는데, 원본에서 실제로 났던 사고다.
    """
    if map_target is not None:
        return map_target
    x_m, y_m, yaw_rad = robot_pose
    dx, dy, dyaw = coord
    cos_yaw, sin_yaw = math.cos(yaw_rad), math.sin(yaw_rad)
    return (
        x_m + dx * cos_yaw - dy * sin_yaw,
        y_m + dx * sin_yaw + dy * cos_yaw,
        yaw_rad + dyaw,
    )
