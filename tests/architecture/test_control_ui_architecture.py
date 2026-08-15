from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROL_UI = ROOT / "control_ui"
APP = CONTROL_UI / "rmf_control_ui"

ALLOWED_CONTROL_UI_ENTRIES = {
    ".gitignore",
    "README.md",
    "UPSTREAM_CONTROL_SYSTEM_COMMIT",
    "rmf_control_ui",
}
ALLOWED_APP_TRACKED_ENTRIES = {
    ".gitignore",
    "README.md",
    "analysis_options.yaml",
    "lib",
    "pubspec.lock",
    "pubspec.yaml",
    "test",
    "web",
}
REMOVED_LEGACY_ENTRIES = {
    ".claude",
    ".rmf_schedule_node.yaml",
    "db",
    "introduction",
    "openrmf",
    "openrmf_app",
    "pinky.txt",
    "project1-ver2.rmfproject",
    "project1.rmfproject",
    "rmf_maps",
    "roboapp",
    "robo_control",
    "robo_core",
    "robo_pinky",
    "warehouse.png",
}
NON_WEB_SHELLS = {"android", "ios", "linux", "macos", "windows"}
FORBIDDEN_RUNTIME_TOKENS = {
    "dart:io",
    "package:mysql",
    "package:sqflite",
    "Process.run",
    "Process.start",
    "ServerSocket",
    "HttpServer",
    "/internal/v1/",
}
FORBIDDEN_BACKEND_LIBRARIES = {
    "database_migration.dart",
    "deployed_map_service.dart",
    "deployment_service.dart",
    "map_project_store.dart",
    "operations_log.dart",
    "project_file_store.dart",
    "project_log.dart",
    "rmf_project_runner.dart",
    "rmf_runtime_service.dart",
    "rmf_task_bridge.dart",
    "robot_link_probe.dart",
    "robot_model_store.dart",
    "robot_sensor_feed.dart",
    "robot_telemetry_bridge.dart",
    "ros2_inspect.dart",
    "slam_map_store.dart",
    "task_store.dart",
    "workcell_policy_store.dart",
    "workspace_layout.dart",
}
GENERATED_PARTS = {
    ".dart_tool",
    ".flutter-plugins-dependencies",
    ".pytest_cache",
    "__pycache__",
    "build",
}


def _tracked_paths() -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "--", "control_ui"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [Path(line) for line in output.splitlines()]


def test_control_ui_is_a_browser_only_gateway_client() -> None:
    assert {path.name for path in CONTROL_UI.iterdir()} == ALLOWED_CONTROL_UI_ENTRIES
    assert all(not (CONTROL_UI / name).exists() for name in REMOVED_LEGACY_ENTRIES)
    assert (APP / "web").is_dir()
    assert all(not (APP / shell).exists() for shell in NON_WEB_SHELLS)

    tracked_paths = _tracked_paths()
    tracked_app_entries = {
        path.parts[2]
        for path in tracked_paths
        if len(path.parts) >= 3 and path.parts[:2] == ("control_ui", "rmf_control_ui")
    }
    assert tracked_app_entries == ALLOWED_APP_TRACKED_ENTRIES

    api_root = APP / "lib" / "trihouse" / "api"
    assert {path.name for path in api_root.glob("*.dart")} == {
        "fms_api.dart",
        "fms_api_client.dart",
        "fms_models.dart",
    }

    violations: list[str] = []
    for path in (APP / "lib").rglob("*.dart"):
        relative = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_RUNTIME_TOKENS:
            if token in text:
                violations.append(f"{relative}:{token}")
        if path.name.endswith("_io.dart"):
            violations.append(f"{relative}:IO implementation")
        if path.name in FORBIDDEN_BACKEND_LIBRARIES:
            violations.append(f"{relative}:backend implementation")
        if path.parent != api_root and (
            "package:http/" in text or "package:web_socket_channel/" in text
        ):
            violations.append(f"{relative}:transport outside FmsApi client")
    assert violations == []

    tracked_generated = [
        str(path)
        for path in tracked_paths
        if GENERATED_PARTS.intersection(path.parts)
        or path.name.startswith("GeneratedPluginRegistrant")
    ]
    assert tracked_generated == []

    provenance = (CONTROL_UI / "UPSTREAM_CONTROL_SYSTEM_COMMIT").read_text().strip()
    assert len(provenance) == 40
    assert all(character in "0123456789abcdef" for character in provenance)
