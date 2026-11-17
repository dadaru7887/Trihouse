"""복구 시뮬레이션 월드: 벽은 지도와 같고, 조명은 한 번만, 원본은 그대로.

    pytest tests/test_recovery_sim_world.py

scripts/recovery_sim/build_world.py 가 만드는 두 월드를 실제 new_map_2 로 검사한다.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("PIL")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "recovery_sim" / "build_world.py"


def _module():
    """scripts/ 는 패키지가 아니라 경로로 불러온다."""
    spec = importlib.util.spec_from_file_location("recovery_sim_build_world", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_walls_are_exactly_the_map_and_the_source_is_untouched(tmp_path):
    build_world = _module()
    before = build_world.DEFAULT_WORLD_SOURCE.read_bytes()

    report = build_world.build(build_world.DEFAULT_MAP, build_world.DEFAULT_WORLD_SOURCE,
                               build_world.DEFAULT_FEATURES, tmp_path)

    assert report["walls_match_map"]
    assert report["occupied_cells"] > 0 and 0 < report["wall_boxes"] < report["occupied_cells"]
    assert build_world.DEFAULT_WORLD_SOURCE.read_bytes() == before
    assert (tmp_path / "preview.png").is_file()
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8")) == report


def test_bringup_gets_a_world_without_walls_so_they_are_not_doubled(tmp_path):
    build_world = _module()
    build_world.build(build_world.DEFAULT_MAP, build_world.DEFAULT_WORLD_SOURCE,
                      build_world.DEFAULT_FEATURES, tmp_path)

    base = (tmp_path / "world_base.sdf").read_text(encoding="utf-8")
    world = (tmp_path / "world.sdf").read_text(encoding="utf-8")

    assert 'model name="walls"' not in base
    assert world.count('model name="walls"') == 1
    for text in (base, world):
        assert text.count(f'name="{build_world.LIGHT_NAME}"') == 1


def test_lighting_is_added_once():
    build_world = _module()
    source = build_world.DEFAULT_WORLD_SOURCE.read_text(encoding="utf-8")

    twice = build_world.add_lighting(build_world.add_lighting(source))

    assert twice.count("<light") == 1
    assert twice.count("<ambient>0.5 0.5 0.5 1</ambient>") == 1


def test_every_measured_waypoint_is_off_the_walls(tmp_path):
    """map 좌표 = Gazebo 좌표. 실측 waypoint 가 벽 안에 있으면 좌표계가 어긋난 것이다."""
    build_world = _module()
    report = build_world.build(build_world.DEFAULT_MAP, build_world.DEFAULT_WORLD_SOURCE,
                               build_world.DEFAULT_FEATURES, tmp_path)

    assert report["waypoints"]
    assert all(point["cell"] == "not_wall" for point in report["waypoints"])
