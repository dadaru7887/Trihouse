"""RMF core 하나와 격리된 두 Pinky namespace를 띄우는 launch 계약."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from launch import LaunchContext
from launch.actions import DeclareLaunchArgument, GroupAction, OpaqueFunction
from launch.utilities import perform_substitutions
from launch_ros.actions import Node, PushRosNamespace


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent
LAUNCH = ROOT / "launch" / "two_pinky_order_demo.launch.py"
FEATURES = (
    REPOSITORY
    / "control_system_test"
    / "rmf_control_ui"
    / "data"
    / "import"
    / "trihouse_test_01_physical_features.jsonl"
)

sys.path.insert(0, str(REPOSITORY))


def _module():
    spec = importlib.util.spec_from_file_location("two_pinky_order_demo", LAUNCH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _charger_pose(location_code: str) -> tuple[float, float, float]:
    """테스트는 launch와 같은 결과를 JSONL에서 직접 읽어 비교한다."""
    for line in FEATURES.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("location_code") == location_code:
            pose = record["map_pose"]
            return pose["x"], pose["y"], pose["yaw"]
    raise AssertionError(f"{location_code} is missing from the authoritative JSONL")


def test_launch_declares_the_two_pinky_demo_cli() -> None:
    description = _module().generate_launch_description()
    names = {
        action.name
        for action in description.entities
        if isinstance(action, DeclareLaunchArgument)
    }

    assert {
        "physical_features_file", "nav_graph", "world", "nav2_params_file",
        "fleet_config", "map_revision", "fleet_name", "fms_base_url",
        "start_rmf_core", "start_gazebo", "start_nav2", "start_rmf_worker",
    } <= names
    assert any(isinstance(action, OpaqueFunction) for action in description.entities)


def test_both_robots_are_pinned_to_their_fixed_charger() -> None:
    module = _module()

    assert module.ROBOT_CHARGERS == (
        ("PK_01", "pinky_01", "TRIHOUSE-TEST-01-CHG-01"),
        ("PK_02", "pinky_02", "TRIHOUSE-TEST-01-CHG-02"),
    )


def test_spawn_poses_come_only_from_the_authoritative_jsonl() -> None:
    poses = _module().charger_spawn_poses(FEATURES)

    assert poses["PK_01"] == pytest.approx(_charger_pose("TRIHOUSE-TEST-01-CHG-01"))
    assert poses["PK_02"] == pytest.approx(_charger_pose("TRIHOUSE-TEST-01-CHG-02"))
    assert poses["PK_01"] != poses["PK_02"]


def test_no_coordinate_literal_is_written_into_the_launch_file() -> None:
    """좌표를 launch 파일에 복제하는 회귀를 막는다."""
    source = LAUNCH.read_text(encoding="utf-8")

    for _robot, _namespace, charger in _module().ROBOT_CHARGERS:
        x, y, yaw = _charger_pose(charger)
        for value in (x, y, yaw):
            assert f"{value}" not in source
    assert "PhysicalFeatureImporter" in source


def _declared_defaults(module, context: LaunchContext) -> dict[str, str]:
    """Resolve every launch argument that declares a default value."""
    defaults: dict[str, str] = {}
    for entity in module.generate_launch_description().entities:
        if not isinstance(entity, DeclareLaunchArgument):
            continue
        if entity.default_value is None:
            # Required arguments have no default; the caller supplies them.
            continue
        defaults[entity.name] = perform_substitutions(
            context, list(entity.default_value)
        )
    return defaults


def _runtime_actions(tmp_path: Path):
    module = _module()
    nav_graph = tmp_path / "0.yaml"
    nav_graph.write_text("levels: {}\n", encoding="utf-8")
    world = tmp_path / "trihouse_test_01.world"
    world.write_text("<sdf/>\n", encoding="utf-8")
    nav2_params = tmp_path / "nav2_params.yaml"
    nav2_params.write_text("amcl: {}\n", encoding="utf-8")
    fleet_config = tmp_path / "fleet.yaml"
    fleet_config.write_text("rmf_fleet: {}\n", encoding="utf-8")

    context = LaunchContext()
    # `ros2 launch` supplies every declared argument before the OpaqueFunction
    # runs; a bare LaunchContext supplies none. Seeding from the launch file's
    # own declared defaults keeps this fixture in step automatically, so adding
    # an argument to the launch file cannot break these tests on its own.
    context.launch_configurations.update(_declared_defaults(module, context))
    context.launch_configurations.update({
        "trihouse_root": str(REPOSITORY),
        "physical_features_file": str(FEATURES),
        "nav_graph": str(nav_graph),
        "world": str(world),
        "nav2_params_file": str(nav2_params),
        "fleet_config": str(fleet_config),
        "map_revision": "trihouse_test_01:fixture",
        "project_name": "trihouse_test_01",
        "rmf_map_name": "L1",
        "fleet_name": "trihouse_pinky",
        "rmf_worker_id": "test-worker",
        "fms_base_url": "http://127.0.0.1:8080",
        "use_sim_time": "true",
        "headless": "true",
        "start_rmf_core": "true",
        "start_gazebo": "false",
        "start_nav2": "true",
        "start_rmf_worker": "false",
        "startup_delay_s": "0",
    })
    return module, context, module._runtime(context)


def test_runtime_starts_one_rmf_core_and_two_isolated_groups(tmp_path: Path) -> None:
    module, context, actions = _runtime_actions(tmp_path)

    timers = [action for action in actions if hasattr(action, "actions")]
    groups = [
        entity
        for timer in timers
        for entity in timer.actions
        if isinstance(entity, GroupAction)
    ]
    assert len(groups) == 2

    namespaces = []
    for group in groups:
        pushes = [
            entity
            for entity in group.get_sub_entities()
            if isinstance(entity, PushRosNamespace)
        ]
        assert len(pushes) == 1
        namespaces.append(
            perform_substitutions(context, pushes[0]._PushROSNamespace__namespace)
        )
    assert namespaces == ["pinky_01", "pinky_02"]


def test_each_group_spawns_its_robot_at_the_imported_charger_pose(
    tmp_path: Path,
) -> None:
    module, context, actions = _runtime_actions(tmp_path)
    poses = module.charger_spawn_poses(FEATURES)

    spawn_arguments = []
    for timer in (action for action in actions if hasattr(action, "actions")):
        for group in timer.actions:
            if not isinstance(group, GroupAction):
                continue
            for entity in group.get_sub_entities():
                if isinstance(entity, Node) and "create" in str(entity.node_executable):
                    spawn_arguments.append(
                        [
                            part.perform(context) if hasattr(part, "perform") else str(part)
                            for argument in entity._Node__arguments
                            for part in (
                                argument if isinstance(argument, list) else [argument]
                            )
                        ]
                    )

    assert len(spawn_arguments) == 2
    for (robot_id, namespace, _charger), arguments in zip(
        module.ROBOT_CHARGERS, spawn_arguments, strict=True
    ):
        x, y, yaw = poses[robot_id]
        assert arguments[arguments.index("-name") + 1] == namespace
        assert float(arguments[arguments.index("-x") + 1]) == pytest.approx(x)
        assert float(arguments[arguments.index("-y") + 1]) == pytest.approx(y)
        assert float(arguments[arguments.index("-Y") + 1]) == pytest.approx(yaw)


def test_every_runtime_interface_stays_inside_the_robot_namespace() -> None:
    module = _module()

    assert "scan" in module.NAMESPACED_INTERFACES
    assert "compute_path_to_pose" in module.NAMESPACED_INTERFACES
    assert "follow_path" in module.NAMESPACED_INTERFACES
    assert "global_costmap/costmap" in module.NAMESPACED_INTERFACES
    assert "local_costmap/costmap" in module.NAMESPACED_INTERFACES
    # 절대 이름은 두 로봇이 서로의 토픽을 덮어쓰게 만든다.
    assert not any(name.startswith("/") for name in module.NAMESPACED_INTERFACES)


def test_missing_bootstrap_graph_or_features_fails_fast(tmp_path: Path) -> None:
    module = _module()
    context = LaunchContext()
    context.launch_configurations.update({
        "physical_features_file": str(tmp_path / "absent.jsonl"),
        "nav_graph": str(tmp_path / "absent.yaml"),
    })

    with pytest.raises(RuntimeError, match="physical-feature JSONL"):
        module._runtime(context)


RMF_CORE_NODES = (
    ("rmf_traffic_ros2", "rmf_traffic_schedule"),
    ("rmf_traffic_ros2", "rmf_traffic_blockade"),
    ("rmf_fleet_adapter", "door_supervisor"),
    ("rmf_fleet_adapter", "lift_supervisor"),
    ("rmf_fleet_adapter", "mutex_group_supervisor"),
    ("rmf_task_ros2", "rmf_task_dispatcher"),
)


def _core_nodes():
    """rmf_core.launch.py 가 실제로 만드는 (package, executable) 목록."""
    core = LAUNCH.with_name("rmf_core.launch.py")
    assert core.is_file()
    spec = importlib.util.spec_from_file_location("rmf_core", core)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    context = LaunchContext()
    context.launch_configurations.update({
        "use_sim_time": "true", "server_uri": "", "initial_map": "L1",
        "lane_width": "0.120", "waypoint_scale": "1.000", "text_scale": "0.600",
        "start_visualization": "false", "building_map_file": "",
    })
    found = []
    for action in module._core(context):
        package = getattr(action, "node_package", None)
        executable = getattr(action, "node_executable", None)
        if package is not None and executable is not None:
            found.append(
                (
                    perform_substitutions(context, package)
                    if not isinstance(package, str)
                    else package,
                    perform_substitutions(context, executable)
                    if not isinstance(executable, str)
                    else executable,
                )
            )
    return found


def test_the_rmf_core_launch_declares_every_required_node() -> None:
    assert set(_core_nodes()) == set(RMF_CORE_NODES)


def test_every_rmf_core_executable_exists_in_this_ros_installation() -> None:
    """`rmf_traffic_ros2` 에 common.launch.xml 이 없어 기동이 깨졌던 회귀를 막는다."""
    import shutil
    import subprocess

    if shutil.which("ros2") is None:
        pytest.skip("ROS 2 is not available on this host")

    for package, executable in _core_nodes():
        listed = subprocess.run(
            ["ros2", "pkg", "executables", package],
            text=True,
            capture_output=True,
            check=False,
        )
        assert listed.returncode == 0, f"unknown package: {package}"
        assert f"{package} {executable}" in listed.stdout.splitlines(), (
            f"{package} has no executable named {executable}"
        )


def test_the_demo_includes_that_core_rather_than_the_energy_bridge() -> None:
    source = LAUNCH.read_text(encoding="utf-8")

    assert "rmf_core.launch.py" in source
    assert "office_energy_bridge.launch.py" not in source
