#!/usr/bin/env python3
"""복구(VLM+RL) 시뮬레이션용 Gazebo 월드를 SLAM 지도에서 만든다.

    python3 scripts/recovery_sim/build_world.py                     # new_map_2
    python3 scripts/recovery_sim/build_world.py --map <지도.yaml> --out <폴더>

만들어지는 것 (기본 `.trihouse/recovery_sim/`):

    world.sdf        벽 + 조명. `gz sim` 이나 `launch_sim.launch.xml` 로 단독 실행할 때
    world_base.sdf   조명만, 벽 없음. `p0_simulation_bringup.sh` 의 PINKY_WORLD 로 줄 때
                     (bringup 이 같은 지도로 벽을 직접 세우므로 벽을 넣으면 두 겹이 된다)
    preview.png      위에서 본 그림: 지도, 생성된 벽 상자(빨강), waypoint(초록), 원점 축
    report.json      벽 상자 수, 지도와 일치 여부, waypoint 별 벽까지 거리

Flow: 원본 world(`control_tower/bringup/p0_world.sdf`, 읽기만 함) -> 조명 추가
-> world_base.sdf -> 지도 점유 셀로 벽 세우기(`p0_runtime_assets.build_world_with_walls`,
bringup 과 같은 함수) -> world.sdf -> 벽 상자를 격자로 되그려 지도 점유 셀과 비교
-> preview.png, report.json. 일치하지 않으면 종료 코드 1.

벽은 지도 좌표 그대로(모델 pose 0) 놓인다. 그래서 Gazebo 의 world 좌표 = 지도의 map
좌표다. 원리와 실행 순서는 docs/guides/recovery-sim-world.md 에 있다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_tower.bringup.p0_runtime_assets import (  # noqa: E402
    WALL_HEIGHT_M, MapGrid, build_world_with_walls, read_map_grid,
)

DEFAULT_MAP = ROOT / "pinky_pro_alpha" / "pinky_navigation" / "map" / "new_map_2.yaml"
DEFAULT_WORLD_SOURCE = ROOT / "control_tower" / "bringup" / "p0_world.sdf"
DEFAULT_FEATURES = (ROOT / "data" / "map_authoring" / "import"
                    / "trihouse_test_01_physical_features.new_map_2.jsonl")
DEFAULT_OUT = ROOT / ".trihouse" / "recovery_sim"

# 원본 p0_world.sdf 에는 <light> 가 없어 카메라는 기본 주변광만으로 찍힌다.
# VLM 과 검출기에 들어갈 화면이므로 위에서 비스듬히 비추는 빛 하나를 넣는다.
# 그림자는 끈다 — 렌더링 비용이 크고, 실물 실험실 조명도 그림자가 옅다.
LIGHT_NAME = "recovery_sun"
LIGHTING = f"""    <!-- scripts/recovery_sim/build_world.py 가 넣은 조명 -->
    <light type="directional" name="{LIGHT_NAME}">
      <cast_shadows>false</cast_shadows>
      <pose>0 0 3 0 0 0</pose>
      <diffuse>0.9 0.9 0.9 1</diffuse>
      <specular>0.2 0.2 0.2 1</specular>
      <direction>-0.4 0.2 -0.9</direction>
    </light>
"""
SCENE_AMBIENT = "<ambient>0.5 0.5 0.5 1</ambient>"


def add_lighting(world_text: str) -> str:
    """world SDF 문자열에 조명과 주변광을 넣는다. 이미 들어 있으면 그대로 둔다."""
    if f'name="{LIGHT_NAME}"' not in world_text:
        closing = world_text.rfind("</world>")
        if closing < 0:
            raise SystemExit("world 원본에 </world> 가 없습니다")
        world_text = world_text[:closing] + LIGHTING + world_text[closing:]
    scene = world_text.find("<scene>")
    if scene >= 0 and "<ambient>" not in world_text[scene:world_text.find("</scene>", scene)]:
        cut = scene + len("<scene>")
        world_text = world_text[:cut] + f"\n      {SCENE_AMBIENT}" + world_text[cut:]
    return world_text


def wall_cells(world_text: str, grid: MapGrid) -> set[tuple[int, int]]:
    """world 의 `walls` 모델 상자들을 지도 격자에 되그려 (행, 열) 집합으로 돌려준다."""
    walls = ElementTree.fromstring(world_text).find(".//model[@name='walls']")
    if walls is None:
        return set()
    origin_x, origin_y = grid.origin
    cells: set[tuple[int, int]] = set()
    for link in walls.findall("link"):
        x, y = (float(v) for v in link.findtext("pose", "").split()[:2])
        sx, sy = (float(v) for v in link.findtext("collision/geometry/box/size").split()[:2])
        first_col = round((x - sx / 2 - origin_x) / grid.resolution)
        last_col = round((x + sx / 2 - origin_x) / grid.resolution) - 1
        first_up = round((y - sy / 2 - origin_y) / grid.resolution)
        last_up = round((y + sy / 2 - origin_y) / grid.resolution) - 1
        for col in range(first_col, last_col + 1):
            for up in range(first_up, last_up + 1):
                cells.add((grid.height - 1 - up, col))
    return cells


def load_waypoints(features: Path) -> list[tuple[str, float, float]]:
    """실측 physical-feature JSONL 에서 (이름, x, y) 를 읽는다. 파일이 없으면 빈 목록."""
    if not features.is_file():
        return []
    points = []
    for line in features.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        pose = record.get("map_pose") or {}
        if "x" in pose and "y" in pose:
            points.append((record["source_id"], float(pose["x"]), float(pose["y"])))
    return points


def cell_of(grid: MapGrid, x: float, y: float) -> tuple[int, int]:
    """map 좌표 (x, y) 가 들어 있는 격자 (행, 열)."""
    col = math.floor((x - grid.origin[0]) / grid.resolution)
    up = math.floor((y - grid.origin[1]) / grid.resolution)
    return grid.height - 1 - up, col


def wall_clearance(grid: MapGrid, x: float, y: float) -> float:
    """(x, y) 에서 가장 가까운 벽 셀 중심까지의 거리 (m)."""
    best = math.inf
    for row, col in grid.occupied:
        cx = grid.origin[0] + (col + 0.5) * grid.resolution
        cy = grid.origin[1] + (grid.height - 1 - row + 0.5) * grid.resolution
        best = min(best, math.hypot(cx - x, cy - y))
    return best


def draw_preview(map_yaml: Path, world_text: str, grid: MapGrid,
                 points: list[tuple[str, float, float]], out: Path, scale: int = 8) -> None:
    """지도 위에 벽 상자, waypoint, 원점 축을 그려 PNG 로 저장한다."""
    from PIL import Image, ImageDraw

    import yaml

    image_name = yaml.safe_load(map_yaml.read_text(encoding="utf-8"))["image"]
    base = Image.open(map_yaml.parent / image_name).convert("RGB")
    canvas = base.resize((grid.width * scale, grid.height * scale), Image.NEAREST)
    draw = ImageDraw.Draw(canvas)

    def pixel(x: float, y: float) -> tuple[float, float]:
        return ((x - grid.origin[0]) / grid.resolution * scale,
                (grid.height - (y - grid.origin[1]) / grid.resolution) * scale)

    walls = ElementTree.fromstring(world_text).find(".//model[@name='walls']")
    for link in [] if walls is None else walls.findall("link"):
        x, y = (float(v) for v in link.findtext("pose", "").split()[:2])
        sx, sy = (float(v) for v in link.findtext("collision/geometry/box/size").split()[:2])
        (x0, y0), (x1, y1) = pixel(x - sx / 2, y + sy / 2), pixel(x + sx / 2, y - sy / 2)
        draw.rectangle([x0, y0, x1 - 1, y1 - 1], outline=(220, 30, 30))

    ox, oy = pixel(0.0, 0.0)                      # map 원점 = Gazebo 원점
    reach = 0.3 / grid.resolution * scale         # 0.3 m 길이의 축
    draw.line([ox, oy, ox + reach, oy], fill=(220, 30, 30), width=3)   # +x
    draw.line([ox, oy, ox, oy - reach], fill=(30, 160, 30), width=3)   # +y
    draw.text((ox + 4, oy + 4), "map/world (0,0)", fill=(0, 0, 160))

    for name, x, y in points:
        px, py = pixel(x, y)
        draw.ellipse([px - 4, py - 4, px + 4, py + 4], fill=(20, 170, 60))
        draw.text((px + 6, py - 6), name, fill=(0, 90, 30))
    canvas.save(out)


def build(map_yaml: Path, world_source: Path, features: Path, out_dir: Path) -> dict:
    """월드 두 벌과 preview, report 를 `out_dir` 에 쓰고 report 를 돌려준다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    base_path, world_path = out_dir / "world_base.sdf", out_dir / "world.sdf"

    base_path.write_text(add_lighting(world_source.read_text(encoding="utf-8")),
                         encoding="utf-8")
    build_world_with_walls(map_yaml, base_path, world_path)

    grid = read_map_grid(map_yaml)
    world_text = world_path.read_text(encoding="utf-8")
    covered = wall_cells(world_text, grid)
    points = load_waypoints(features)
    draw_preview(map_yaml, world_text, grid, points, out_dir / "preview.png")

    def status(row: int, col: int) -> str:
        if not (0 <= row < grid.height and 0 <= col < grid.width):
            return "outside_map"
        return "wall" if (row, col) in grid.occupied else "not_wall"

    report = {
        "map": str(map_yaml),
        "resolution_m": grid.resolution,
        "size_m": [round(grid.width * grid.resolution, 3), round(grid.height * grid.resolution, 3)],
        "origin": list(grid.origin),
        "wall_height_m": WALL_HEIGHT_M,
        "occupied_cells": len(grid.occupied),
        "wall_boxes": len(ElementTree.fromstring(world_text).findall(
            ".//model[@name='walls']/link")),
        "walls_match_map": covered == set(grid.occupied),
        "cells_missing_a_wall": len(set(grid.occupied) - covered),
        "walls_where_map_is_free": len(covered - set(grid.occupied)),
        "waypoints": [{"name": name, "x": x, "y": y,
                       "cell": status(*cell_of(grid, x, y)),
                       "nearest_wall_m": round(wall_clearance(grid, x, y), 3)}
                      for name, x, y in points],
        "files": {"world": str(world_path), "world_base": str(base_path),
                  "preview": str(out_dir / "preview.png")},
    }
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    """명령줄을 읽어 월드를 만들고, 요약을 출력한다. 벽이 지도와 다르면 1."""
    parser = argparse.ArgumentParser(description="SLAM 지도에서 복구 시뮬레이션 Gazebo 월드를 만든다")
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP, help="지도 yaml (Nav2 와 같은 것)")
    parser.add_argument("--world-source", type=Path, default=DEFAULT_WORLD_SOURCE,
                        help="바닥면·물리 설정이 든 원본 world. 읽기만 한다")
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES,
                        help="waypoint 실측 JSONL. preview 와 거리 확인에만 쓴다")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="출력 폴더")
    args = parser.parse_args(argv)

    report = build(args.map, args.world_source, args.features, args.out)
    width, height = report["size_m"]
    print(f"지도 {Path(report['map']).name}: {width} m x {height} m, 셀 {report['resolution_m']} m")
    print(f"벽: 점유 셀 {report['occupied_cells']} 개 -> 상자 {report['wall_boxes']} 개, "
          f"높이 {report['wall_height_m']} m")
    print(f"지도와 일치: {'예' if report['walls_match_map'] else '아니오'} "
          f"(벽 빠진 셀 {report['cells_missing_a_wall']}, 지도에 없는 벽 "
          f"{report['walls_where_map_is_free']})")
    for point in report["waypoints"]:
        print(f"  {point['name']:<34} ({point['x']:+.3f}, {point['y']:+.3f})  "
              f"{point['cell']:<11} 벽까지 {point['nearest_wall_m']:.3f} m")
    for key, path in report["files"].items():
        print(f"{key:<11} {path}")
    return 0 if report["walls_match_map"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
