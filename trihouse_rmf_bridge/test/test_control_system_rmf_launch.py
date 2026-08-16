"""control_system 통합 launch의 CLI 및 단일 adapter 계약."""

import importlib.util
from pathlib import Path

from launch import LaunchContext
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction


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

    assert '"nav2_adapter.py" in generated_nav2_launch.read_text' in source
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


def test_runtime_selects_only_requested_robot_spawn_and_nav2(tmp_path: Path) -> None:
    """전체 생성 bringup을 include해 OMX와 두 번째 Pinky가 따라오는 회귀를 막는다."""
    spec = importlib.util.spec_from_file_location("control_system_rmf_selected", LAUNCH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    control_root = tmp_path / "control_system"
    project_dir = control_root / "rmf_maps" / "project1"
    robot_dir = project_dir / "robots" / "PK_01"
    (project_dir / "nav_graphs").mkdir(parents=True)
    robot_dir.mkdir(parents=True)
    for relative in (
        "project1.launch.xml",
        "project1_bringup.launch.xml",
        "project1_nav2.launch.xml",
        "project1.world",
        "project1_gz_bridge.yaml",
        "nav2_map/project1.yaml",
        "nav_graphs/0.yaml",
        "robots/PK_01/spawn.launch.xml",
        "robots/PK_01/nav2.launch.xml",
    ):
        path = project_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<launch/>\n" if path.suffix == ".xml" else "{}\n")

    rmf_root = tmp_path / "rmf_ws"
    (rmf_root / "install").mkdir(parents=True)
    runtime_root = tmp_path / "runtime"
    fleet_config = tmp_path / "fleet.yaml"
    fleet_config.write_text("rmf_fleet: {}\n")

    context = LaunchContext()
    context.launch_configurations.update({
        "rmf_ws_root": str(rmf_root),
        "control_system_root": str(control_root),
        "runtime_state_root": str(runtime_root),
        "project_name": "project1",
        "robot_id": "PK_01",
        "robot_namespace": "pinky_01",
        "map_revision": "project1:fixture",
        "control_host": "127.0.0.1",
        "control_port": "8788",
        "fleet_config": str(fleet_config),
        "rmf_map_name": "L1",
        "charger_waypoint": "충전1",
        "fms_base_url": "http://127.0.0.1:8080",
        "fleet_name": "project1_pinky",
        "rmf_worker_id": "test-worker",
        "trihouse_root": str(tmp_path),
        "event_outbox_max_pending": "1000",
        "use_sim_time": "true",
        "headless": "true",
        "start_control_system_core": "true",
        "start_gazebo": "true",
        "start_nav2": "true",
        "start_pinky_runtime": "true",
        "start_trihouse_adapter": "true",
        "start_rmf_worker": "true",
        "startup_delay_s": "0",
        "battery_percentage": "1.0",
        "charging": "false",
        "discharge_percent_per_second": "0.0",
    })

    actions = module._runtime(context)
    included = set()
    for action in actions:
        if not isinstance(action, IncludeLaunchDescription):
            continue
        action.launch_description_source.get_launch_description(context)
        included.add(action.launch_description_source.location)

    assert str(robot_dir / "spawn.launch.xml") in included
    assert str(robot_dir / "nav2.launch.xml") in included
    assert str(project_dir / "project1_bringup.launch.xml") not in included
    assert str(project_dir / "project1_nav2.launch.xml") not in included
