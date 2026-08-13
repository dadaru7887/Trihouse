"""control_system 원본을 보존하며 Trihouse 검증용 사본을 준비한다."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET


class OverlayError(RuntimeError):
    pass


_TRIHOUSE_IGNORE_BLOCK = """

# Trihouse integration candidate: reproducible/generated artifacts
**/.dart_tool/
**/build/
**/install/
**/log/
**/__pycache__/
**/.pytest_cache/
**/node_modules/
*.py[cod]
*.log
*.err.log
*.pid
*.pgid
rmf_maps/.backups/
rmf_maps/warehouse.tar.gz
rmf_maps/*/nav_visualization/
"""


def _run_git(arguments: list[str], *, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip() or str(error)
        raise OverlayError(f"git 실행 실패: {detail}") from error
    return result.stdout.strip()


def _clone_source(source: Path, destination: Path) -> None:
    if not (source / ".git").exists():
        raise OverlayError(f"control_system Git 저장소가 아닙니다: {source}")
    _run_git([
        "clone", "--local", "--no-hardlinks", str(source), str(destination),
    ])
    _run_git(["switch", "-c", "trihouse-integration"], cwd=destination)


def _remove_generated_artifacts(destination: Path) -> None:
    directory_names = {
        ".dart_tool", "build", "install", "log", "__pycache__",
        ".pytest_cache", "node_modules", "nav_visualization",
    }
    for path in sorted(destination.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if ".git" in path.parts:
            continue
        if path.is_dir() and path.name in directory_names:
            shutil.rmtree(path)
            continue
        if not path.is_file() and not path.is_symlink():
            continue
        if (
            path.suffix in {".pyc", ".log", ".pid", ".pgid"}
            or path.name == "warehouse.tar.gz"
        ):
            path.unlink()
    backups = destination / "rmf_maps" / ".backups"
    if backups.exists():
        shutil.rmtree(backups)

    ignore_path = destination / ".gitignore"
    current = ignore_path.read_text(encoding="utf-8") if ignore_path.exists() else ""
    if "# Trihouse integration candidate" not in current:
        ignore_path.write_text(
            current.rstrip() + _TRIHOUSE_IGNORE_BLOCK,
            encoding="utf-8",
        )


def _remove_native_adapter(path: Path) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    for executable in list(root.findall("executable")):
        if "nav2_adapter.py" in executable.attrib.get("cmd", ""):
            root.remove(executable)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="unicode", xml_declaration=True)


def _patch_robot_nav2_launch(path: Path) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    controller = next(
        (
            node for node in root.iter("node")
            if node.attrib.get("exec") == "controller_server"
        ),
        None,
    )
    if controller is None:
        raise OverlayError(f"controller_server가 없습니다: {path}")
    if not any(
        remap.attrib.get("from") == "cmd_vel"
        and remap.attrib.get("to") == "cmd_vel_nav"
        for remap in controller.findall("remap")
    ):
        ET.SubElement(controller, "remap", {"from": "cmd_vel", "to": "cmd_vel_nav"})
    ET.indent(tree, space="  ")
    tree.write(path, encoding="unicode", xml_declaration=True)


def prepare_overlay(source: Path, destination: Path, project: str) -> Path:
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_dir():
        raise OverlayError(f"control_system 원본이 없습니다: {source}")
    if destination.exists():
        raise OverlayError(
            f"기존 경로를 덮어쓰지 않습니다: {destination}. 새 경로를 지정하세요."
        )
    project_dir = source / "rmf_maps" / project
    if not project_dir.is_dir():
        raise OverlayError(f"RMF project가 없습니다: {project_dir}")

    _clone_source(source, destination)
    _remove_generated_artifacts(destination)
    copied_project = destination / "rmf_maps" / project
    _remove_native_adapter(copied_project / f"{project}_nav2.launch.xml")
    robot_launches = sorted((copied_project / "robots").glob("*/nav2.launch.xml"))
    if not robot_launches:
        raise OverlayError(f"robot Nav2 launch가 없습니다: {copied_project / 'robots'}")
    for robot_launch in robot_launches:
        _patch_robot_nav2_launch(robot_launch)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "control_system을 독립 Git clone으로 복사하고 생성물과 adapter 충돌을 "
            "제거합니다."
        )
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--project", default="project1")
    args = parser.parse_args()
    try:
        result = prepare_overlay(args.source, args.destination, args.project)
    except OverlayError as error:
        parser.error(str(error))
    print(result)
    return 0
