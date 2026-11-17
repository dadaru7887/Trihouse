"""승인된 복구 좌표까지 가는 길을 지금 지도로 검사하는 규칙 (6C-Lite)."""

import math

import pytest

from trihouse_pinky_fleet.costmap_view import (
    FOOTPRINT_INSCRIBED_RADIUS_M,
    CostmapSnapshot,
    CostmapView,
)
from trihouse_pinky_fleet.recovery_path_check import (
    rollout,
    rollout_blocked,
    target_pose,
)
from trihouse_pinky_safety.geometry import (
    FOOTPRINT_INSCRIBED_RADIUS_M as SAFETY_INSCRIBED_RADIUS_M,
)


def grid(occupied: set[tuple[int, int]] = frozenset(), width: int = 40,
         height: int = 40, resolution: float = 0.05) -> CostmapSnapshot:
    """원점 (-1, -1) 에서 시작하는 빈 지도. `occupied` 셀만 LETHAL."""
    cells = [0] * (width * height)
    for column, row in occupied:
        cells[row * width + column] = 100
    return CostmapSnapshot(
        grid=cells, width=width, height=height, resolution=resolution,
        origin_x=-1.0, origin_y=-1.0, frame_id="map",
    )


def cell_of(x_m: float, y_m: float, resolution: float = 0.05) -> tuple[int, int]:
    return int((x_m + 1.0) / resolution), int((y_m + 1.0) / resolution)


def test_footprint_radius_matches_the_safety_package() -> None:
    """두 패키지가 같은 몸을 다른 크기로 알고 있으면 안 된다."""
    assert FOOTPRINT_INSCRIBED_RADIUS_M == SAFETY_INSCRIBED_RADIUS_M


def test_open_path_passes() -> None:
    view = CostmapView(global_=grid())

    report = rollout((0.0, 0.0, 0.0), (0.4, 0.0, 0.0), view)

    assert report.passed
    assert len(report.steps) == 8


def test_short_moves_are_not_sampled_below_the_costmap_resolution() -> None:
    """0.2 m 를 8 등분하면 2.5 cm 간격이라 같은 셀을 반복 조회할 뿐이다.

    복구 이동은 대부분 envelope(0.25 m) 안이므로 이 축소가 기본 동작이 된다.
    """
    view = CostmapView(global_=grid())

    report = rollout((0.0, 0.0, 0.0), (0.2, 0.0, 0.0), view)

    assert report.passed
    assert len(report.steps) == 4


def test_obstacle_between_start_and_goal_blocks_an_otherwise_free_goal() -> None:
    """이 검사가 존재하는 이유 그 자체.

    목적지 셀은 비어 있는데 가는 길 중간이 막힌 경우다. 좌표 값만 보는
    canonicalization 은 이것을 통과시킨다.
    """
    blocked = {cell_of(0.10, 0.0)}
    view = CostmapView(global_=grid(blocked))

    assert view.costmap_free(0.2, 0.0) is True
    report = rollout((0.0, 0.0, 0.0), (0.2, 0.0, 0.0), view)

    assert not report.passed
    # 어느 규칙이 먼저 잡았는지는 중요하지 않다. 발자국 검사가 중심 셀보다 먼저
    # 걸리는 것이 정상이다 — 내접원 표본이 옆 셀까지 닿기 때문이고, 그쪽이 더
    # 보수적이다.
    assert report.detail.split("@")[0] in {"COSTMAP_OCCUPIED", "FOOTPRINT_BLOCKED"}


def test_first_violation_stops_the_walk() -> None:
    """막힌 지점 뒤의 좌표는 로봇이 도달하지 못하므로 조회할 의미가 없다."""
    view = CostmapView(global_=grid({cell_of(0.05, 0.0)}))

    report = rollout((0.0, 0.0, 0.0), (0.4, 0.0, 0.0), view)

    assert not report.passed
    assert len(report.steps) < 8
    assert not report.steps[-1].passed


def test_footprint_wider_than_the_gap_is_rejected_even_on_a_free_centre_line() -> None:
    """중심선은 비어도 몸이 안 들어가면 못 간다."""
    side = {cell_of(0.2, FOOTPRINT_INSCRIBED_RADIUS_M)}
    view = CostmapView(global_=grid(side))

    assert view.costmap_free(0.2, 0.0) is True
    assert view.footprint_fits(0.2, 0.0, 0.0) is False


def test_unknown_cells_are_not_treated_as_free() -> None:
    """지도 밖은 "모른다" 이지 "비었다" 가 아니다."""
    view = CostmapView(global_=grid())

    assert view.costmap_free(50.0, 50.0) is False


def test_missing_costmap_fails_closed() -> None:
    """지도를 못 받았으면 비어 있다고 말할 근거가 없다."""
    assert rollout_blocked((0.0, 0.0, 0.0), (0.2, 0.0, 0.0), CostmapView()) == (
        "COSTMAP_UNAVAILABLE"
    )
    assert rollout_blocked((0.0, 0.0, 0.0), (0.2, 0.0, 0.0), None) == (
        "COSTMAP_UNAVAILABLE"
    )


def test_keep_out_zone_blocks_a_geometrically_free_path() -> None:
    view = CostmapView(
        global_=grid(),
        keep_out_polygons=[((0.1, -0.1), (0.1, 0.1), (0.3, 0.1), (0.3, -0.1))],
    )

    assert rollout_blocked((0.0, 0.0, 0.0), (0.2, 0.0, 0.0), view).startswith(
        "KEEP_OUT_ZONE"
    )


def test_local_costmap_is_preferred_and_falls_back_outside_its_window() -> None:
    """local 은 실시간 LiDAR 를 담고, 그 창 밖은 global 이 답한다."""
    local = CostmapSnapshot(
        grid=[100] * 4, width=2, height=2, resolution=0.05,
        origin_x=0.0, origin_y=0.0, frame_id="odom",
    )
    view = CostmapView(local=local, global_=grid())

    # local 창 안: 점유로 보인다.
    assert view.costmap_free(0.02, 0.02) is False
    # local 창 밖: global 이 답한다.
    assert view.costmap_free(0.5, 0.5) is True


def test_untransformable_local_costmap_is_skipped_rather_than_queried_wrongly() -> None:
    """프레임 변환을 못 얻으면 local 을 건너뛴다. 틀린 좌표 조회보다 낫다."""
    local = CostmapSnapshot(
        grid=[100] * 4, width=2, height=2, resolution=0.05,
        origin_x=0.0, origin_y=0.0, frame_id="odom",
    )
    view = CostmapView(local=local, global_=grid(), map_to_local=lambda x, y: None)

    assert view.costmap_free(0.02, 0.02) is True


def test_relative_offsets_and_absolute_rejoin_targets_are_not_confused() -> None:
    """REJOIN 만 절대 좌표다. 상대값을 map 좌표로 조회하면 엉뚱한 곳을 검사한다."""
    robot = (1.0, 2.0, math.pi / 2)

    relative = target_pose(robot, (0.2, 0.0, 0.0), None)
    absolute = target_pose(robot, (0.2, 0.0, 0.0), (5.0, 5.0, 0.0))

    assert relative[0] == pytest.approx(1.0)
    assert relative[1] == pytest.approx(2.2)
    assert absolute == (5.0, 5.0, 0.0)
