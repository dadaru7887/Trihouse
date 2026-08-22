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
    / "data"
    / "map_authoring"
    / "import"
    / "trihouse_test_01_physical_features.new_map_2.jsonl"
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
        "narrow_zones_file",
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


def test_simulated_lidar_rejects_returns_from_the_robot_model() -> None:
    module = _module()
    first = module._robot_description("pinky_01")
    second = module._robot_description("pinky_02")

    assert 'type="gpu_lidar"' in first
    assert "<min>0.19</min>" in first
    # EN: Gazebo GPU lidar renders collision geometry, so visual-only masks do not
    # remove the Pinky's own returns. Keep the simulated ray plane above the body.
    # KO: Gazebo GPU LiDAR는 collision 형상을 보므로 visual mask로 자기반사가
    # 사라지지 않는다. 시뮬레이션 광선 높이를 차체 위로 유지한다.
    assert "<pose>0 0 0.055 0 0 0</pose>" in first
    assert "<pose>0 0 0.055 0 0 0</pose>" in second
    assert "visibility_flags" not in first
    assert "visibility_mask" not in first


def test_simulation_stop_distance_fits_the_measured_approach_clearance() -> None:
    source = LAUNCH.read_text(encoding="utf-8")

    assert '"stop_distance_m": 0.10' in source


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


def _runtime_actions(tmp_path: Path, **overrides: str):
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
    context.launch_configurations.update(overrides)
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


def test_nav2_never_runs_composed_so_each_robot_keeps_its_own_localisation(
    tmp_path: Path,
) -> None:
    """nav2_bringup 의 `ComposableNode` 에는 namespace 인자가 없다.

    합성을 켜면 바깥 PushRosNamespace 가 컨테이너에만 붙고 적재된 AMCL 과
    map_server 에는 전파되지 않는다. 그러면 두 로봇이 루트의 `/amcl_pose` 와
    `/map` 하나를 함께 쓰게 되어 위치추정이 서로를 덮어쓴다. 실제로 그렇게 떴다.
    """
    module, context, actions = _runtime_actions(tmp_path)

    includes = []
    for timer in (action for action in actions if hasattr(action, "actions")):
        for group in timer.actions:
            if not isinstance(group, GroupAction):
                continue
            for entity in group.get_sub_entities():
                arguments = getattr(entity, "launch_arguments", None)
                if arguments is None:
                    continue
                # launch_arguments 는 평범한 문자열일 수도, 치환 목록일 수도
                # 있다. 문자열을 list() 로 감싸면 글자 단위로 쪼개진다.
                def _text(value):
                    if isinstance(value, str):
                        return value
                    if isinstance(value, (list, tuple)):
                        return perform_substitutions(context, list(value))
                    return perform_substitutions(context, [value])

                resolved = {_text(name): _text(value) for name, value in arguments}
                if "use_composition" in resolved:
                    includes.append(resolved)

    assert includes, "nav2 bringup include not found"
    for resolved in includes:
        assert resolved["use_composition"] == "False"


def test_one_robot_can_be_launched_alone(tmp_path: Path) -> None:
    """로봇 한 대만 띄우는 길이 있어야 한다.

    로봇 두 대의 전체 스택(Gazebo + Nav2 두 벌 + Open-RMF + 로봇당 온보드 노드
    여섯 개)은 개발 PC 한 대의 용량을 넘는다. 실측으로 load average 가 60~90 이었고,
    그 상태에서는 Nav2 의 lifecycle manager 가 `map_server/get_state` 를 기다리다
    포기하며(`Failed to bring up all requested nodes`) 새로 붙는 노드도 토픽을
    발견하지 못한다. 설정 결함이 아니라 부하이므로, 주문 경로를 증명할 때는 로봇을
    한 대로 줄여 변수를 없애는 편이 빠르다.

    두 대 구성을 지우지는 않는다. 교통 조정과 병목 예약은 두 대가 있어야 의미가 있다.
    """
    module, context, actions = _runtime_actions(tmp_path, robots="PK_01")

    namespaces = []
    for timer in (action for action in actions if hasattr(action, "actions")):
        for group in timer.actions:
            if not isinstance(group, GroupAction):
                continue
            pushes = [
                entity
                for entity in group.get_sub_entities()
                if isinstance(entity, PushRosNamespace)
            ]
            if pushes:
                namespaces.append(
                    perform_substitutions(
                        context, pushes[0]._PushROSNamespace__namespace
                    )
                )

    assert namespaces == ["pinky_01"]

    # 그룹 밖의 bridge 도 같이 줄어야 한다. 남으면 없는 로봇의 gz 토픽을 구독한다.
    mentioned = []
    for node in _nodes_outside_groups(actions):
        if "parameter_bridge" not in str(node.node_executable):
            continue
        for argument in getattr(node, "_Node__arguments", None) or []:
            mentioned.append(
                argument if isinstance(argument, str)
                else perform_substitutions(context, [argument])
            )
        for _source, target in _remappings(context, node):
            mentioned.append(target)

    assert any("pinky_01" in text for text in mentioned), mentioned
    assert not any("pinky_02" in text for text in mentioned), mentioned


def test_an_unknown_robot_id_fails_instead_of_starting_nothing(tmp_path: Path) -> None:
    """오타가 조용히 "로봇 0대" 로 끝나면 무엇이 잘못됐는지 알 수 없다."""
    with pytest.raises(RuntimeError, match="PK_99"):
        _runtime_actions(tmp_path, robots="PK_99")


def _remappings(context, node: Node) -> list[tuple[str, str]]:
    """`Node` 에 걸린 remap 규칙을 문자열 쌍으로 푼다."""
    raw = getattr(node, "_Node__remappings", None) or []
    resolved = []
    for source, target in raw:
        def _text(value):
            if isinstance(value, str):
                return value
            if isinstance(value, (list, tuple)):
                return perform_substitutions(context, list(value))
            return perform_substitutions(context, [value])

        resolved.append((_text(source), _text(target)))
    return resolved


def _nodes_in_groups(context, actions):
    """namespace 그룹 안의 Node 를 (namespace, node) 로 낸다."""
    for timer in (action for action in actions if hasattr(action, "actions")):
        for group in timer.actions:
            if not isinstance(group, GroupAction):
                continue
            entities = list(group.get_sub_entities())
            pushes = [e for e in entities if isinstance(e, PushRosNamespace)]
            if not pushes:
                continue
            namespace = perform_substitutions(
                context, pushes[0]._PushROSNamespace__namespace
            )
            for entity in entities:
                if isinstance(entity, Node):
                    yield namespace, entity


def _nodes_outside_groups(actions):
    for timer in (action for action in actions if hasattr(action, "actions")):
        for entity in timer.actions:
            if isinstance(entity, Node):
                yield entity


def test_tf_reaches_nav2_because_nav2_listens_inside_the_namespace(
    tmp_path: Path,
) -> None:
    """nav2 는 TF 를 전역 `/tf` 에서 읽지 않는다.

    `nav2_bringup` 의 localization/navigation launch 는 모든 노드에
    `[('/tf', 'tf'), ('/tf_static', 'tf_static')]` 을 무조건 건다. 상대 이름이
    되었으므로 바깥 PushRosNamespace 가 접두사를 붙여 nav2 노드는
    `/pinky_01/tf` 와 `/pinky_01/tf_static` 을 듣는다.

    그런데 이 시스템의 TF 발행자는 전역 `/tf` 에 쓴다. 그래서 한동안
    `/tf` 는 발행자 3 구독자 0, `/pinky_02/tf_static` 은 발행자 0 구독자 8 이었다.
    AMCL 의 TF 버퍼가 비어 스캔이 전량 폐기되고(`Message Filter dropping
    message`), 위치추정이 한 번도 돌지 않아 `amcl_pose` 가 나오지 않았다.
    그러면 status 의 `frame_id` 가 `map` 이 되지 못해 RMF adapter 가 로봇을
    거부하고 주문이 배정되지 않는다. costmap 도 TF 없이는 활성되지 못해
    controller_server 활성이 실패했다.

    프레임 이름에는 이미 로봇 namespace 가 붙어 있으므로(URDF 의 `frame_prefix`)
    같은 트리를 로봇 namespace 안에서 주고받아도 서로 섞이지 않는다.
    """
    module, context, actions = _runtime_actions(tmp_path)

    publishers = [
        (namespace, node)
        for namespace, node in _nodes_in_groups(context, actions)
        if "robot_state_publisher" in str(node.node_executable)
    ]
    assert len(publishers) == 2, "로봇마다 robot_state_publisher 가 하나 있어야 한다"

    for _namespace, node in publishers:
        remaps = dict(_remappings(context, node))
        # 상대 이름으로 remap 해야 PushRosNamespace 가 접두사를 붙인다.
        assert remaps.get("/tf") == "tf"
        assert remaps.get("/tf_static") == "tf_static"


def test_the_gazebo_odom_transform_is_bridged_into_each_namespace(
    tmp_path: Path,
) -> None:
    """정적 사슬만으로는 부족하다. `odom -> base_footprint` 가 있어야 한다.

    그 변환은 Gazebo 의 DiffDrive 플러그인이 gz `/tf` 로 내보내고 bridge 가
    ROS 로 넘긴다. 전역 `/tf` 로만 넘기면 nav2 는 그것을 보지 못하므로 로봇
    namespace 안으로도 넣어야 한다. bridge 는 준 이름을 gz 와 ROS 양쪽에 쓰기
    때문에 namespace 밖에서 띄우고 ROS 쪽만 remap 한다.
    """
    module, context, actions = _runtime_actions(tmp_path)

    namespaces = [namespace for _robot, namespace, _charger in module.ROBOT_CHARGERS]
    targets = set()
    for node in _nodes_outside_groups(actions):
        for source, target in _remappings(context, node):
            if source == "/tf":
                targets.add(target)

    assert targets == {f"/{namespace}/tf" for namespace in namespaces}


def test_each_robot_gets_the_nodes_that_make_it_dispatchable(tmp_path: Path) -> None:
    """`dispatchable` 이 false 면 RMF 는 그 로봇에 작업을 주지 않는다.

    adapter 는 status 의 `dispatchable` 을 자기 `ready` 로 복사하고, false 면
    `PINKY_NOT_READY` 로 로봇을 RMF 에 내보내지 않는다. 주행과 위치추정이
    완벽해도 그렇다.

    그 값은 `status_node` 가 스스로 정하지 않는다. 다른 노드들의 telemetry 를
    모아 `build_status` 에 넘긴 결과이고, 그중 넷은 여기서 띄우지 않으면 영영
    false 로 남는다 — 오류가 아니라 발행자가 없는 것이라 조용하다.

      battery_stale             <- trihouse/battery            (sim_hardware)
      nav_unavailable           <- trihouse/readiness          (readiness_checker)
      battery_not_dispatchable  <- trihouse/battery/policy_state (battery_policy,
                                   그 입력은 battery_condition 이 낸다)
      control_link_offline      <- trihouse/fms/state          (fleet_gateway)

    `safety_supervisor`·`recovery_health`·`fleet_node` 는 여기에 필요하지 않다.
    safety 는 기본값이 이미 clear 이고 나머지는 이 판정에 들어가지 않는다.
    """
    module, context, actions = _runtime_actions(tmp_path)

    required = {
        "sim_hardware",
        "readiness_checker",
        "battery_condition",
        "battery_policy",
        "fleet_gateway",
        "status_node",
    }

    by_namespace: dict[str, set[str]] = {}
    for namespace, node in _nodes_in_groups(context, actions):
        by_namespace.setdefault(namespace, set()).add(str(node.node_executable))

    expected = [namespace for _robot, namespace, _charger in module.ROBOT_CHARGERS]
    assert sorted(by_namespace) == sorted(expected)
    for namespace in expected:
        missing = required - by_namespace[namespace]
        assert not missing, f"{namespace} 에 없는 노드: {sorted(missing)}"


def test_each_robot_keeps_its_own_event_outbox(tmp_path: Path) -> None:
    """outbox 는 event identity 를 재시작 간 유지하는 저장소다.

    `fleet_gateway` 의 기본값은 `/tmp/trihouse_event_outbox_<pid>.sqlite3` 라서
    프로세스마다 새로 생긴다. 그러면 session 과 sequence 가 매번 초기화되어
    재전송·ACK 의 근거가 사라진다. 로봇마다 고정된 경로를 준다.
    """
    module, context, actions = _runtime_actions(tmp_path)

    def _text(value) -> str:
        # launch_ros 는 파라미터의 키와 값을 모두 치환 목록으로 정규화한다.
        # 그래서 문자열로 그대로 비교할 수 없다.
        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple)):
            return perform_substitutions(context, list(value))
        return perform_substitutions(context, [value])

    paths = {}
    for namespace, node in _nodes_in_groups(context, actions):
        if "fleet_gateway" not in str(node.node_executable):
            continue
        for parameter in node._Node__parameters:
            if not hasattr(parameter, "items"):
                continue
            for key, value in parameter.items():
                if _text(key) == "event_outbox_path":
                    paths[namespace] = _text(value)

    expected = [namespace for _robot, namespace, _charger in module.ROBOT_CHARGERS]
    assert sorted(paths) == sorted(expected)
    # 로봇끼리 같은 파일을 쓰면 sequence 가 서로를 덮어쓴다.
    assert len(set(paths.values())) == len(expected)
    for namespace, path in paths.items():
        assert namespace in path
        assert not path.startswith("/tmp/"), path


def _nav2_includes(context, actions) -> list[dict[str, str]]:
    """`bringup_launch.py` include 로 넘어가는 인자를 로봇 순서대로 모은다."""

    def _text(value):
        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple)):
            return perform_substitutions(context, list(value))
        return perform_substitutions(context, [value])

    includes = []
    for timer in (action for action in actions if hasattr(action, "actions")):
        for group in timer.actions:
            if not isinstance(group, GroupAction):
                continue
            for entity in group.get_sub_entities():
                arguments = getattr(entity, "launch_arguments", None)
                if arguments is None:
                    continue
                resolved = {_text(name): _text(value) for name, value in arguments}
                if "use_composition" in resolved:
                    includes.append(resolved)
    return includes


def test_nav2_gets_the_namespace_so_its_parameter_keys_match_the_node_names(
    tmp_path: Path,
) -> None:
    """`namespace` 는 파라미터 root key 를 정하는 값이기도 하다.

    nav2_bringup 은 `RewrittenYaml(root_key=namespace)` 로 파라미터 파일 전체를
    namespace 아래에 감싼다. 빈 문자열을 주면 그 감싸기가 사라져서 키가
    `controller_server` 로 남는데, 노드는 바깥 PushRosNamespace 때문에
    `/pinky_01/controller_server` 다. 키가 어긋나면 파라미터가 한 개도 적용되지
    않고 노드는 조용히 기본값으로 뜬다 — controller_server 는 기본 플러그인인
    DWB 를 집어들고 `No critics defined for FollowPath` 로 죽었고, AMCL 은
    `set_initial_pose` 를 못 받아 위치추정을 시작하지 못했다.

    이중 접힘은 `use_namespace` 가 켜져 있을 때만 생긴다. 노드 이름에 namespace
    를 입히는 것은 bringup 안의 `PushROSNamespace` 이고 그것은
    `IfCondition(use_namespace)` 로 묶여 있다. 하위 launch 는 어떤 Node 에도
    namespace 를 붙이지 않고 주변 namespace 를 물려받는다. 그래서 이름은 바깥
    PushRosNamespace 하나가, 파라미터 키는 이 인자가 맡는다.
    """
    module, context, actions = _runtime_actions(tmp_path)

    includes = _nav2_includes(context, actions)
    assert includes, "nav2 bringup include not found"

    expected = [namespace for _robot, namespace, _charger in module.ROBOT_CHARGERS]
    assert [resolved["namespace"] for resolved in includes] == expected
    for resolved in includes:
        # 이름을 두 번 입히지 않도록 이것은 계속 꺼져 있어야 한다.
        assert resolved["use_namespace"] == "false"


def test_the_fleet_adapter_is_given_the_name_the_nav_graph_actually_uses() -> None:
    """충전기 이름이 두 갈래면 로봇이 fleet 에 등록되지 못한다.

    `build_nav_graph` 는 waypoint 정점을 `rmf_waypoint_name`(`charging_station_01`)
    으로 이름 짓는데 adapter 에는 `location_code`(`TRIHOUSE-TEST-01-CHG-01`)가
    넘어갔다. 그러면 adapter 가 이렇게 찍고 로봇을 fleet 에 넣지 않는다.

      Cannot find a waypoint named [TRIHOUSE-TEST-01-CHG-01] in the navigation
      graph of fleet [project1_pinky] ... We will not add the robot to the fleet

    로봇이 fleet 에 없으면 낙찰이 나지 않아 주문이 로봇까지 가지 못한다.
    2026-08-18 단일 로봇 시뮬에서 실제로 관측했다.
    """
    module = _module()
    graph_names = module.charger_graph_names(FEATURES)

    assert graph_names["PK_01"] == "charging_station_01"
    assert graph_names["PK_02"] == "charging_station_02"


def test_every_charger_graph_name_exists_in_the_generated_nav_graph() -> None:
    """이름을 손으로 맞추지 않고 같은 JSONL 에서 나온 것인지 확인한다."""
    import yaml

    from control_tower.bringup.p0_runtime_assets import build_nav_graph, load_features

    module = _module()
    waypoints, bottlenecks = load_features(FEATURES)
    graph = yaml.safe_load(build_nav_graph("trihouse_test_01", waypoints, bottlenecks))
    vertex_names = {
        vertex[2]["name"]
        for level in graph["levels"].values()
        for vertex in level["vertices"]
    }

    for robot_id, name in module.charger_graph_names(FEATURES).items():
        assert name in vertex_names, f"{robot_id}: {name} 이 nav_graph 에 없다"


def test_each_group_serves_the_transport_action(tmp_path: Path) -> None:
    """로봇마다 ExecuteTransport 서버가 있어야 한다.

    RMF fleet adapter 는 낙찰된 작업을 `trihouse/transport/execute` action 으로
    로봇에 넘긴다. 그 서버는 `fleet_node` 가 연다. 시뮬 launch 가 그것을 빼면
    adapter 는 "ExecuteTransport action server 가 없습니다" 만 반복하고 로봇은
    영원히 움직이지 않는다. 2026-08-19 에 job 10 이 이 자리에서 멈췄다.
    """
    _, _, actions = _runtime_actions(tmp_path)

    timers = [action for action in actions if hasattr(action, "actions")]
    groups = [
        entity
        for timer in timers
        for entity in timer.actions
        if isinstance(entity, GroupAction)
    ]

    for group in groups:
        executables = [
            entity.node_executable
            for entity in group.get_sub_entities()
            if isinstance(entity, Node)
        ]
        assert "fleet_node" in executables, executables


def test_each_group_bridges_nav2_velocity_to_the_motors(tmp_path: Path) -> None:
    """Nav2 의 속도 명령이 모터까지 가는 경로가 있어야 한다.

    launch 는 Nav2 를 `cmd_vel -> cmd_vel_nav` 로 remap 한다. 모터용 `cmd_vel` 은
    `safety_supervisor` 가 단독으로 소유하며, 그 노드가 `cmd_vel_nav` 를 받아 안전
    gate 를 통과시킨 뒤 발행한다. gz bridge 는 `cmd_vel` 을 Gazebo 로 넘긴다.

    그 노드가 없으면 `cmd_vel_nav` 와 `cmd_vel` 사이가 끊겨 **로봇이 영원히
    움직이지 않는다.** 경로는 계획되고 step 은 `running` 이 되므로 로그만 보면
    정상으로 보인다. 2026-08-19 에 job 13 이 이 자리에서 멈췄다.

    실기 launch 에는 처음부터 있었다.
    """
    _, _, actions = _runtime_actions(tmp_path)

    timers = [action for action in actions if hasattr(action, "actions")]
    groups = [
        entity
        for timer in timers
        for entity in timer.actions
        if isinstance(entity, GroupAction)
    ]

    for group in groups:
        executables = [
            entity.node_executable
            for entity in group.get_sub_entities()
            if isinstance(entity, Node)
        ]
        assert "safety_supervisor" in executables, executables
