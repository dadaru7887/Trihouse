"""control_system 통합 launch의 CLI 및 단일 adapter 계약."""

import importlib.util
from pathlib import Path

from launch.actions import DeclareLaunchArgument, OpaqueFunction


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "launch" / "control_system_rmf.launch.py"


def test_exact_filename_and_path_arguments_are_public_cli_contract() -> None:
    assert LAUNCH.name == "control_system_rmf.launch.py"
    spec = importlib.util.spec_from_file_location("control_system_rmf", LAUNCH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    description = module.generate_launch_description()
    names = {
        action.name for action in description.entities
        if isinstance(action, DeclareLaunchArgument)
    }

    assert {
        "control_system_root", "project_name", "fleet_config",
        "runtime_state_root",
        "fms_base_url", "robot_id", "robot_namespace", "map_revision",
        "start_control_system_core", "start_gazebo", "start_nav2",
        "start_pinky_runtime", "start_trihouse_adapter",
    } <= names
    assert any(isinstance(action, OpaqueFunction) for action in description.entities)


def test_launch_rejects_native_adapter_and_routes_nav2_through_safety() -> None:
    source = LAUNCH.read_text(encoding="utf-8")

    assert '"nav2_adapter.py" in nav2_launch.read_text' in source
    assert '("/cmd_vel_nav", f"{robot_prefix}/cmd_vel_nav")' in source
    assert '("/cmd_vel", f"{robot_prefix}/cmd_vel")' in source
    assert '"pinky_easy_fleet_adapter.launch.py"' in source
    assert 'robot_status_topic = f"{robot_prefix}/trihouse/status"' in source
    assert 'transport_action = f"{robot_prefix}/trihouse/transport/execute"' in source


def test_event_outbox_uses_explicit_runtime_root_and_sanitized_namespace() -> None:
    source = LAUNCH.read_text(encoding="utf-8")

    assert 'LaunchConfiguration("runtime_state_root")' in source
    assert 'control_root / "runtime"' not in source
    assert '_safe_path_token(robot_namespace.perform(context))' in source
