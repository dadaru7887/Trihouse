from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROL_UI = ROOT / "control_ui"
APP = CONTROL_UI / "rmf_control_ui"
LIB = APP / "lib"
PRESENTATION = LIB / "trihouse" / "presentation"
FEATURES = LIB / "trihouse" / "features"

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
FORBIDDEN_IMPORTS = {
    "dart:ffi",
    "dart:io",
    "package:mysql1/mysql1.dart",
    "package:sqflite/sqflite.dart",
}
TRANSPORT_IMPORT_PREFIXES = (
    "dart:html",
    "dart:js_interop",
    "package:http/",
    "package:web/",
    "package:web_socket_channel/",
)
# Browser-only shims that touch a web library for a local capability the Gateway
# does not provide (file selection). They carry no Gateway transport, so they are
# allowed to live with the feature that owns them instead of inside `api/`.
BROWSER_CAPABILITY_SHIMS = {
    "trihouse/features/maps/map_source_picker_web.dart",
}
GATEWAY_TRANSPORT_PREFIXES = (
    "package:http/",
    "package:web_socket_channel/",
)
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
REQUIRED_PRESENTATION_CLASSES = {
    "ControlAppShell",
    "ControlNavigationRail",
    "ControlTopBar",
    "MainDashboard",
    "MapProjectPage",
    "MapWorkspace",
    "RobotOperationsPage",
    "TaskManagementPage",
    "OperationsAnalyticsPage",
}
FEATURE_PAGE_CLASSES = {
    "MainDashboard",
    "MapProjectPage",
    "RobotOperationsPage",
    "TaskManagementPage",
    "OperationsAnalyticsPage",
}
REQUIRED_DIAGNOSTIC_MODELS = {
    "operations_log_models.dart",
    "rmf_runtime_models.dart",
    "robot_sensor_models.dart",
    "robot_telemetry_models.dart",
}
GENERATED_PARTS = {
    ".dart_tool",
    ".flutter-plugins-dependencies",
    ".pytest_cache",
    "__pycache__",
    "build",
}
DIRECTIVE = re.compile(r"^\s*(?:import|export|part)\s+['\"]([^'\"]+)", re.MULTILINE)
CLASS_DECLARATION = re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)")


def _tracked_paths() -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "--", "control_ui"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [Path(line) for line in output.splitlines()]


def _dart_imports(path: Path) -> set[str]:
    return set(DIRECTIVE.findall(path.read_text(encoding="utf-8")))


def _without_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//.*?$", "", text, flags=re.MULTILINE)


def _declared_dependencies() -> set[str]:
    dependencies: set[str] = set()
    section: str | None = None
    for line in (APP / "pubspec.yaml").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith(" "):
            section = line.removesuffix(":")
            continue
        if section not in {"dependencies", "dev_dependencies"}:
            continue
        match = re.match(r"^  ([a-zA-Z0-9_]+):", line)
        if match:
            dependencies.add(match.group(1))
    return dependencies


def _used_packages() -> set[str]:
    used: set[str] = set()
    for path in [*LIB.rglob("*.dart"), *(APP / "test").rglob("*.dart")]:
        for directive in _dart_imports(path):
            if directive.startswith("package:"):
                used.add(directive.split("/", 1)[0].removeprefix("package:"))
    analysis = (APP / "analysis_options.yaml").read_text(encoding="utf-8")
    used.update(re.findall(r"package:([a-zA-Z0-9_]+)/", analysis))
    return used


def test_legacy_backends_and_non_web_shells_stay_removed() -> None:
    assert all(not (CONTROL_UI / name).exists() for name in REMOVED_LEGACY_ENTRIES)
    assert (APP / "web").is_dir()
    assert all(not (APP / shell).exists() for shell in NON_WEB_SHELLS)
    assert (CONTROL_UI / "UPSTREAM_CONTROL_SYSTEM_COMMIT").is_file()


def test_runtime_import_graph_has_one_browser_gateway_boundary() -> None:
    violations: list[str] = []
    api_root = LIB / "trihouse" / "api"
    for path in LIB.rglob("*.dart"):
        relative = path.relative_to(ROOT)
        imports = _dart_imports(path)
        forbidden = sorted(imports.intersection(FORBIDDEN_IMPORTS))
        for directive in forbidden:
            violations.append(f"{relative}: forbidden import {directive}")
        inside_api = api_root in path.parents
        shim = path.relative_to(LIB).as_posix() in BROWSER_CAPABILITY_SHIMS
        for directive in imports:
            if inside_api:
                continue
            if directive.startswith(GATEWAY_TRANSPORT_PREFIXES) or (
                directive.startswith(TRANSPORT_IMPORT_PREFIXES) and not shim
            ):
                violations.append(f"{relative}: transport outside API boundary {directive}")
        if path.name.endswith("_io.dart"):
            violations.append(f"{relative}: IO implementation")
        if path.name in FORBIDDEN_BACKEND_LIBRARIES:
            violations.append(f"{relative}: backend implementation")
        runtime_text = _without_comments(path.read_text(encoding="utf-8"))
        if "/internal/v1/" in runtime_text:
            violations.append(f"{relative}: private Gateway route")
    assert violations == []


def test_team_a_presentation_foundation_depends_on_fms_api() -> None:
    # P0 moved order/map pages under `trihouse/features/`; the shell and shared
    # widgets stay under `trihouse/presentation/`. Both are UI-owned surfaces.
    dart_files = [*PRESENTATION.rglob("*.dart"), *FEATURES.rglob("*.dart")]
    declared: dict[str, Path] = {}
    for path in dart_files:
        text = path.read_text(encoding="utf-8")
        for class_name in CLASS_DECLARATION.findall(text):
            declared[class_name] = path
    assert REQUIRED_PRESENTATION_CLASSES <= declared.keys()

    for class_name in FEATURE_PAGE_CLASSES:
        imports = _dart_imports(declared[class_name])
        assert any(imported.endswith("/fms_api.dart") for imported in imports), class_name
        assert not any(imported.endswith("/fms_api_client.dart") for imported in imports)

    model_names = {path.name for path in LIB.glob("*.dart")}
    assert REQUIRED_DIAGNOSTIC_MODELS <= model_names


def test_direct_dependencies_are_used_by_retained_browser_code() -> None:
    assert _declared_dependencies() <= _used_packages()


def test_generated_artifacts_are_not_tracked() -> None:
    tracked_generated = [
        str(path)
        for path in _tracked_paths()
        if GENERATED_PARTS.intersection(path.parts)
        or path.name.startswith("GeneratedPluginRegistrant")
    ]
    assert tracked_generated == []
