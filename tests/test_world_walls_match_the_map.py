"""Gazebo world 의 벽은 발행된 지도에서만 나온다.

## 왜

`p0_world.sdf` 는 `ground_plane` 하나뿐이라 시뮬레이션 안에 부딪힐 것이 없었다.
라이다가 빈 공간만 보므로 지역 costmap 은 늘 비어 있고 AMCL 은 스캔 정합 없이
오도메트리로만 갔다. 그 상태의 "성공" 은 실물로 전이되지 않는다.

벽을 손으로 만들면 **세 번째 진실**이 생긴다 — 원장이 발행한 지도, Nav2 의
static layer, 그리고 Gazebo 의 물리. 셋이 갈라지면 로봇이 "도착했다" 고 말하는
자리와 실제로 서 있는 자리가 어긋나고, 그 어긋남은 로그를 시각까지 맞춰 가며
뒤져야 드러난다. 그래서 벽은 **Nav2 가 도는 것과 같은 yaml** 에서 생성한다.

## 이 테스트가 지키는 것

생성된 벽이 덮는 격자 집합이 지도의 점유 셀 집합과 **정확히** 같을 것.
병합 알고리즘이 어떻게 바뀌든 이 등식은 유지되어야 한다.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest
import yaml

from control_tower.bringup.p0_runtime_assets import build_world_with_walls, read_map_grid

ROOT = Path(__file__).resolve().parents[1]
MAPS = ROOT / "control_ui" / "rmf_control_ui" / "data" / "rmf_maps"
WORLD_SOURCE = ROOT / "control_tower" / "bringup" / "p0_world.sdf"

# 라이다 평면의 높이. `pinky.urdf.xacro` 에서 base_footprint -> base_link 0.028,
# -> rplidar_mount 0.067, -> rplidar_link 0.030 을 더한 값이다. 벽이 이보다
# 낮으면 스캔이 그냥 통과해 벽이 없는 것과 같아진다.
LIDAR_PLANE_M = 0.125


def _wall_boxes(sdf_text: str) -> list[tuple[tuple[float, ...], tuple[float, ...]]]:
    """생성된 SDF 에서 (pose, box size) 쌍을 뽑는다."""
    root = ElementTree.fromstring(sdf_text)
    walls = root.find(".//model[@name='walls']")
    assert walls is not None, "walls 모델이 없다"
    boxes = []
    for link in walls.findall("link"):
        pose = tuple(float(v) for v in link.findtext("pose", "").split())
        size_text = link.findtext("collision/geometry/box/size")
        assert size_text is not None, f"{link.get('name')} 에 collision box 가 없다"
        boxes.append((pose, tuple(float(v) for v in size_text.split())))
    return boxes


def _covered_cells(sdf_text: str, resolution: float, origin: tuple[float, float], height: int):
    """벽 상자들을 지도 격자에 되돌려 그린다. 셀 좌표 집합을 반환한다."""
    origin_x, origin_y = origin
    covered: set[tuple[int, int]] = set()
    for pose, size in _wall_boxes(sdf_text):
        x, y = pose[0], pose[1]
        size_x, size_y = size[0], size[1]
        first_column = round((x - size_x / 2 - origin_x) / resolution)
        last_column = round((x + size_x / 2 - origin_x) / resolution) - 1
        first_bottom = round((y - size_y / 2 - origin_y) / resolution)
        last_bottom = round((y + size_y / 2 - origin_y) / resolution) - 1
        for column in range(first_column, last_column + 1):
            for bottom in range(first_bottom, last_bottom + 1):
                covered.add((height - 1 - bottom, column))
    return covered


def _write_map(directory: Path, rows: list[str], resolution: float = 0.05) -> Path:
    """'#' 점유, '.' 자유, '+' 미확인 으로 작은 P5 지도를 만든다."""
    shades = {"#": 0, ".": 254, "+": 205}
    width, height = len(rows[0]), len(rows)
    pixels = bytes(shades[character] for row in rows for character in row)
    image = directory / "tiny.pgm"
    image.write_bytes(b"P5\n%d %d\n255\n" % (width, height) + pixels)
    map_yaml = directory / "tiny.yaml"
    map_yaml.write_text(
        yaml.safe_dump(
            {
                "image": "tiny.pgm",
                "mode": "trinary",
                "resolution": resolution,
                "origin": [0.0, 0.0, 0.0],
                "negate": 0,
                "occupied_thresh": 0.65,
                "free_thresh": 0.196,
            }
        ),
        encoding="utf-8",
    )
    return map_yaml


def test_walls_cover_exactly_the_occupied_cells(tmp_path: Path) -> None:
    """실제 지도로. 하나라도 빠지거나 더 생기면 물리와 costmap 이 갈라진다."""
    map_yaml = MAPS / "trihouse_map_01.yaml"
    destination = tmp_path / "world.sdf"
    build_world_with_walls(map_yaml, WORLD_SOURCE, destination)

    grid = read_map_grid(map_yaml)
    covered = _covered_cells(
        destination.read_text(encoding="utf-8"), grid.resolution, grid.origin, grid.height
    )
    assert covered == grid.occupied


def test_unknown_cells_do_not_become_walls(tmp_path: Path) -> None:
    """미확인 셀은 대부분 방 밖이다. 벽으로 세우면 없는 벽이 생긴다."""
    map_yaml = _write_map(tmp_path, ["###", "+.+", "###"])
    destination = tmp_path / "world.sdf"
    build_world_with_walls(map_yaml, WORLD_SOURCE, destination)

    grid = read_map_grid(map_yaml)
    covered = _covered_cells(
        destination.read_text(encoding="utf-8"), grid.resolution, grid.origin, grid.height
    )
    assert (1, 0) not in covered and (1, 2) not in covered
    assert covered == grid.occupied


def test_the_boxes_do_not_overlap(tmp_path: Path) -> None:
    """겹친 상자는 Gazebo 에서 접촉 계산을 늘리기만 하고 얻는 것이 없다."""
    map_yaml = MAPS / "trihouse_map_01.yaml"
    destination = tmp_path / "world.sdf"
    build_world_with_walls(map_yaml, WORLD_SOURCE, destination)

    grid = read_map_grid(map_yaml)
    seen: set[tuple[int, int]] = set()
    for pose, size in _wall_boxes(destination.read_text(encoding="utf-8")):
        cells = _covered_cells(
            f"<sdf><model name='walls'><link name='one'>"
            f"<pose>{' '.join(str(v) for v in pose)}</pose>"
            f"<collision><geometry><box><size>{' '.join(str(v) for v in size)}</size>"
            f"</box></geometry></collision></link></model></sdf>",
            grid.resolution,
            grid.origin,
            grid.height,
        )
        assert not (cells & seen), "상자가 겹친다"
        seen |= cells


def test_the_walls_reach_the_lidar_plane(tmp_path: Path) -> None:
    """벽이 스캔 평면보다 낮으면 벽이 없는 것과 같다."""
    map_yaml = MAPS / "trihouse_map_01.yaml"
    destination = tmp_path / "world.sdf"
    build_world_with_walls(map_yaml, WORLD_SOURCE, destination)

    for pose, size in _wall_boxes(destination.read_text(encoding="utf-8")):
        bottom, top = pose[2] - size[2] / 2, pose[2] + size[2] / 2
        assert bottom <= 0.0, "벽이 바닥에서 떠 있다"
        assert top > LIDAR_PLANE_M, f"벽 높이 {top} m 가 라이다 평면 {LIDAR_PLANE_M} m 보다 낮다"


def test_the_source_world_survives(tmp_path: Path) -> None:
    """바닥면이 사라지면 로봇이 떨어진다. 원본은 읽기만 한다."""
    map_yaml = MAPS / "trihouse_map_01.yaml"
    destination = tmp_path / "world.sdf"
    before = WORLD_SOURCE.read_text(encoding="utf-8")
    build_world_with_walls(map_yaml, WORLD_SOURCE, destination)

    root = ElementTree.fromstring(destination.read_text(encoding="utf-8"))
    assert root.find(".//model[@name='ground_plane']") is not None
    assert WORLD_SOURCE.read_text(encoding="utf-8") == before


def test_a_png_disguised_as_a_pgm_is_read(tmp_path: Path) -> None:
    """`new_map_2.pgm` 은 확장자만 pgm 이고 내용은 PNG 다."""
    map_yaml = MAPS / "new_map_2.yaml"
    destination = tmp_path / "world.sdf"
    build_world_with_walls(map_yaml, WORLD_SOURCE, destination)

    grid = read_map_grid(map_yaml)
    covered = _covered_cells(
        destination.read_text(encoding="utf-8"), grid.resolution, grid.origin, grid.height
    )
    assert covered == grid.occupied
    assert grid.occupied, "이 지도에 점유 셀이 하나도 없다"
