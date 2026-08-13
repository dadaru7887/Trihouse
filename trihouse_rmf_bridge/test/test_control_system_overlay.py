"""control_system 원본 보존과 adapter 단일 소유권을 검사한다."""

import sys
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trihouse_rmf_bridge.control_system_overlay import (  # noqa: E402
    OverlayError, prepare_overlay,
)


NAV2 = """<?xml version='1.0'?>
<launch>
  <executable cmd="python3 /tmp/project1_nav2_adapter.py -c fleet.yaml"/>
  <executable cmd="python3 /tmp/project1_sensor_relay.py -o /tmp/out"/>
</launch>
"""
ROBOT_NAV2 = """<?xml version='1.0'?>
<launch><node pkg="nav2_controller" exec="controller_server"/></launch>
"""


def _commit_source(source: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=source, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@trihouse.local"],
        cwd=source, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Trihouse Test"],
        cwd=source, check=True,
    )
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(
        ["git", "commit", "-m", "fixture"], cwd=source, check=True,
        stdout=subprocess.DEVNULL,
    )


def _source_fixture(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "control_system"
    project = source / "rmf_maps" / "project1"
    project.mkdir(parents=True)
    nav2 = project / "project1_nav2.launch.xml"
    nav2.write_text(NAV2, encoding="utf-8")
    robot_nav2 = project / "robots" / "PK_01" / "nav2.launch.xml"
    robot_nav2.parent.mkdir(parents=True)
    robot_nav2.write_text(ROBOT_NAV2, encoding="utf-8")
    (source / ".gitignore").write_text("/log/\n", encoding="utf-8")
    _commit_source(source)
    return source, nav2


def test_overlay_is_an_independent_git_clone_and_patches_command_ownership(
    tmp_path: Path,
) -> None:
    source, nav2 = _source_fixture(tmp_path)
    destination = tmp_path / "control_system_test"

    prepare_overlay(source, destination, "project1")

    copied = (destination / "rmf_maps" / "project1" / nav2.name).read_text()
    assert "project1_nav2_adapter.py" not in copied
    assert "project1_sensor_relay.py" in copied
    copied_robot = (
        destination / "rmf_maps" / "project1" / "robots" / "PK_01" / "nav2.launch.xml"
    ).read_text()
    assert 'from="cmd_vel" to="cmd_vel_nav"' in copied_robot
    assert "project1_nav2_adapter.py" in nav2.read_text()
    assert (destination / ".git").is_dir()
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=destination,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert branch == "trihouse-integration"


def test_overlay_removes_tracked_generated_files_and_adds_ignore_rules(
    tmp_path: Path,
) -> None:
    source, _ = _source_fixture(tmp_path)
    generated = (
        source / "rmf_maps" / ".backups" / "project1-old" / "project1.log"
    )
    generated.parent.mkdir(parents=True)
    generated.write_text("runtime", encoding="utf-8")
    dart_cache = source / "robo_core" / ".dart_tool" / "cache.bin"
    dart_cache.parent.mkdir(parents=True)
    dart_cache.write_bytes(b"cache")
    subprocess.run(["git", "add", "-f", "."], cwd=source, check=True)
    subprocess.run(
        ["git", "commit", "-m", "tracked generated fixture"], cwd=source,
        check=True, stdout=subprocess.DEVNULL,
    )
    destination = tmp_path / "control_system_test"

    prepare_overlay(source, destination, "project1")

    assert not (destination / "rmf_maps" / ".backups").exists()
    assert not (destination / "robo_core" / ".dart_tool").exists()
    ignore = (destination / ".gitignore").read_text(encoding="utf-8")
    assert "rmf_maps/.backups/" in ignore
    assert "**/.dart_tool/" in ignore
    assert "**/build/" in ignore


def test_overlay_refuses_to_overwrite_an_existing_test_tree(tmp_path: Path) -> None:
    source, _ = _source_fixture(tmp_path)
    destination = tmp_path / "control_system_test"
    destination.mkdir()

    with pytest.raises(OverlayError, match="덮어쓰지"):
        prepare_overlay(source, destination, "project1")
