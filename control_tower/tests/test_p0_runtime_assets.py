"""공유 지도 위에서 두 로봇이 각자 위치추정하기 위한 파생 파라미터 계약.

로봇마다 slam_toolbox 를 돌리면 같은 창고의 지도를 각자 따로 만들고, 두 `map`
프레임이 일치하지 않는다. 그러면 병목 예약도 lane 충돌도 근거를 잃는다. 공유
지도로 바꾸는 순간 AMCL 초기 pose 가 필수가 되므로, 그 값이 승인된 JSONL 의
충전기 좌표에서만 오는지를 여기서 지킨다.
"""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "control_tower" / "bringup" / "p0_runtime_assets.py"
FEATURES = (
    ROOT / "control_ui" / "rmf_control_ui" / "data" / "import"
    / "trihouse_test_01_physical_features.jsonl"
)


def _module():
    spec = importlib.util.spec_from_file_location("p0_runtime_assets", ASSETS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _charger_pose_from_source(location_code: str) -> tuple[float, float, float]:
    for line in FEATURES.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("location_code") == location_code:
            pose = record["map_pose"]
            return pose["x"], pose["y"], pose["yaw"]
    raise AssertionError(f"missing charger: {location_code}")


def test_each_robot_starts_localised_at_its_own_fixed_charger() -> None:
    """AMCL 이 초기 pose 없이 시작하면 지도 전체에 입자를 흩뿌린다."""
    module = _module()
    waypoints, _ = module.load_features(FEATURES)

    assert module.charger_pose(waypoints, "PK_01") == _charger_pose_from_source(
        "TRIHOUSE-TEST-01-CHG-01"
    )
    assert module.charger_pose(waypoints, "PK_02") == _charger_pose_from_source(
        "TRIHOUSE-TEST-01-CHG-02"
    )


def test_the_two_robots_do_not_share_a_starting_pose() -> None:
    module = _module()
    waypoints, _ = module.load_features(FEATURES)

    assert module.charger_pose(waypoints, "PK_01") != module.charger_pose(
        waypoints, "PK_02"
    )


def test_the_charger_pairing_matches_what_the_gateway_enforces() -> None:
    """Gateway 는 다른 짝을 FIXED_CHARGER_MISMATCH 로 거절한다."""
    from control_tower.task_manager.assignment import CHARGER_BY_MOBILE

    assert _module().CHARGER_BY_ROBOT == CHARGER_BY_MOBILE


def test_an_unknown_robot_has_no_starting_pose() -> None:
    module = _module()
    waypoints, _ = module.load_features(FEATURES)

    assert module.charger_pose(waypoints, "PK_09") is None


def test_a_missing_charger_record_stops_the_bringup(tmp_path: Path) -> None:
    """좌표를 지어내느니 기동을 멈추는 편이 낫다."""
    module = _module()

    with pytest.raises(SystemExit):
        module.charger_pose({}, "PK_01")


def test_the_derived_parameters_carry_the_initial_pose(tmp_path: Path) -> None:
    module = _module()
    source = tmp_path / "nav2.yaml"
    source.write_text(
        yaml.safe_dump(
            {
                "amcl": {
                    "ros__parameters": {
                        "base_frame_id": "base_footprint",
                        "odom_frame_id": "odom",
                        # 원본의 리스트 형태. nav2_amcl 은 개별 파라미터를
                        # 선언하므로 이대로 두면 조용히 무시된다.
                        "set_initial_pose": True,
                        "initial_pose": [0, 0, 0],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    destination = tmp_path / "pinky_01.yaml"

    module.derive_nav2_params(
        source, "pinky_01", destination, initial_pose=(1.5, -2.5, 0.75)
    )

    amcl = yaml.safe_load(destination.read_text(encoding="utf-8"))["amcl"][
        "ros__parameters"
    ]
    assert amcl["set_initial_pose"] is True
    assert amcl["initial_pose"] == {"x": 1.5, "y": -2.5, "z": 0.0, "yaw": 0.75}


def test_frames_are_split_per_robot_but_the_map_frame_is_shared(tmp_path: Path) -> None:
    """공유 지도의 요점이 여기다. `map` 까지 갈라지면 두 로봇은 다른 세계에 산다."""
    module = _module()
    source = tmp_path / "nav2.yaml"
    source.write_text(
        yaml.safe_dump(
            {
                "amcl": {
                    "ros__parameters": {
                        "base_frame_id": "base_footprint",
                        "odom_frame_id": "odom",
                        "global_frame_id": "map",
                    }
                },
                "local_costmap": {
                    "local_costmap": {
                        "ros__parameters": {"robot_base_frame": "base_footprint"}
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    destination = tmp_path / "pinky_02.yaml"

    module.derive_nav2_params(source, "pinky_02", destination)

    derived = yaml.safe_load(destination.read_text(encoding="utf-8"))
    amcl = derived["amcl"]["ros__parameters"]
    assert amcl["base_frame_id"] == "pinky_02/base_footprint"
    assert amcl["odom_frame_id"] == "pinky_02/odom"
    assert amcl["global_frame_id"] == "map"
    assert (
        derived["local_costmap"]["local_costmap"]["ros__parameters"]["robot_base_frame"]
        == "pinky_02/base_footprint"
    )


def test_omitting_the_initial_pose_leaves_the_source_untouched(tmp_path: Path) -> None:
    """`TRIHOUSE_NAV2_SLAM=true` 로 되돌릴 때는 초기 pose 를 심지 않는다."""
    module = _module()
    source = tmp_path / "nav2.yaml"
    source.write_text(
        yaml.safe_dump({"amcl": {"ros__parameters": {"base_frame_id": "base_footprint"}}}),
        encoding="utf-8",
    )
    destination = tmp_path / "pinky_01.yaml"

    module.derive_nav2_params(source, "pinky_01", destination)

    amcl = yaml.safe_load(destination.read_text(encoding="utf-8"))["amcl"][
        "ros__parameters"
    ]
    assert "initial_pose" not in amcl


def test_collision_monitor_is_configured_because_it_publishes_the_only_cmd_vel(
    tmp_path: Path,
) -> None:
    """이 절이 없으면 로봇은 한 발도 움직이지 못한다.

    `nav2_bringup/launch/navigation_launch.py` 는 controller_server 와
    velocity_smoother 와 behavior_server 의 `cmd_vel` 을 전부 `cmd_vel_nav` 로
    remap 하고, collision_monitor 에만 remap 을 걸지 않는다. 그래서
    `cmd_vel` 을 실제로 발행하는 노드는 collision_monitor 하나뿐이고 그것이
    Gazebo bridge 가 듣는 토픽이다.

    그런데 collision_monitor 는 `lifecycle_nodes` 에 무조건 들어 있는데
    벤더 params 에는 그 절이 없다. `observation_sources` 는 기본값이 없어서
    노드는 `parameter 'observation_sources' is not initialized` 로 configure 에
    실패하고, navigation lifecycle 전체가 그 자리에서 중단된다.
    """
    module = _module()
    source = tmp_path / "nav2.yaml"
    source.write_text(
        yaml.safe_dump({"amcl": {"ros__parameters": {"base_frame_id": "base_footprint"}}}),
        encoding="utf-8",
    )
    destination = tmp_path / "pinky_02.yaml"

    module.derive_nav2_params(source, "pinky_02", destination)

    monitor = yaml.safe_load(destination.read_text(encoding="utf-8"))[
        "collision_monitor"
    ]["ros__parameters"]

    # 관측원이 있어야 configure 를 통과한다.
    assert monitor["observation_sources"] == ["scan"]
    # 이웃 로봇의 스캔을 보면 서로를 장애물로 여겨 둘 다 멈춘다.
    assert monitor["scan"]["topic"] == "/pinky_02/scan"
    assert monitor["base_frame_id"] == "pinky_02/base_footprint"
    assert monitor["odom_frame_id"] == "pinky_02/odom"
    # 출력은 상대 이름이어야 namespace 안의 `/pinky_02/cmd_vel` 로 나간다.
    # 절대 이름으로 적으면 두 로봇이 루트의 한 토픽을 함께 밀어 서로를 덮어쓴다.
    assert monitor["cmd_vel_out_topic"] == "cmd_vel"
    assert monitor["cmd_vel_in_topic"] == "cmd_vel_smoothed"
    assert (
        monitor["FootprintApproach"]["footprint_topic"]
        == "local_costmap/published_footprint"
    )
    # 선언한 폴리곤 이름은 반드시 같은 이름의 절을 가져야 한다.
    for name in monitor["polygons"]:
        assert name in monitor


def test_docking_server_configures_even_though_p0_never_docks(tmp_path: Path) -> None:
    """P0 는 도킹을 쓰지 않지만 이 절이 없으면 주행 자체가 뜨지 않는다.

    `docking_server` 는 navigation `lifecycle_nodes` 의 마지막 항목이고 목록에
    무조건 들어 있다. `dock_plugins` 가 없으면 `Charging dock plugins not given!`
    으로 configure 에 실패하고, lifecycle_manager 는 그 하나 때문에 navigation
    전체를 abort 한다 — 앞의 노드가 모두 정상이어도 그렇다.

    충전은 RMF 가 충전기 waypoint 로 관리하므로 dock 인스턴스(`docks`)는 두지
    않는다. 노드가 configure 를 통과해 조용히 대기하는 것이 여기서 필요한 전부다.
    """
    module = _module()
    source = tmp_path / "nav2.yaml"
    source.write_text(
        yaml.safe_dump({"amcl": {"ros__parameters": {"base_frame_id": "base_footprint"}}}),
        encoding="utf-8",
    )
    destination = tmp_path / "pinky_02.yaml"

    module.derive_nav2_params(source, "pinky_02", destination)

    docking = yaml.safe_load(destination.read_text(encoding="utf-8"))["docking_server"][
        "ros__parameters"
    ]

    assert docking["dock_plugins"], "dock_plugins 가 비면 configure 에서 죽는다"
    # 선언한 plugin 이름은 반드시 같은 이름의 절을 가져야 한다.
    for name in docking["dock_plugins"]:
        assert docking[name]["plugin"]

    # 프레임은 로봇마다 갈라져야 한다. URDF 가 frame_prefix 로 접두사를 붙인다.
    assert docking["base_frame"] == "pinky_02/base_link"
    assert docking["fixed_frame"] == "pinky_02/odom"

    # 실제 도킹 동작은 P0 범위가 아니다. 인스턴스를 두면 쓰는 것처럼 보인다.
    assert "docks" not in docking
    # 외부 검출 pose 는 aruco 파이프라인을 전제한다. P0 에는 없다.
    assert docking[docking["dock_plugins"][0]]["use_external_detection_pose"] is False


def test_a_source_that_already_configures_collision_monitor_wins(tmp_path: Path) -> None:
    """벤더가 나중에 이 절을 채우면 우리 기본값이 그것을 덮어써서는 안 된다."""
    module = _module()
    source = tmp_path / "nav2.yaml"
    source.write_text(
        yaml.safe_dump(
            {
                "collision_monitor": {
                    "ros__parameters": {
                        "observation_sources": ["front_scan"],
                        "front_scan": {"type": "scan", "topic": "scan"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    destination = tmp_path / "pinky_01.yaml"

    module.derive_nav2_params(source, "pinky_01", destination)

    monitor = yaml.safe_load(destination.read_text(encoding="utf-8"))[
        "collision_monitor"
    ]["ros__parameters"]
    assert monitor["observation_sources"] == ["front_scan"]
    assert monitor["front_scan"]["topic"] == "/pinky_01/scan"


def test_root_key_wraps_the_document_for_launchers_without_rewritten_yaml(tmp_path):
    """벤더 XML 은 `<param from>` 으로 원본을 그대로 넘긴다.

    `nav2_bringup` 은 `RewrittenYaml(root_key=namespace)` 로 최상위 키를 스스로
    감싸 주지만 실기 `pinky_navigation/launch/bringup_launch.xml` 에는 그 장치가
    없다. 그러면 `/pinky_01/amcl` 노드가 맨 키 `amcl:` 과 매칭되지 않아 파라미터가
    한 개도 적용되지 않는다.
    """
    module = _module()
    source = tmp_path / "nav2_params.yaml"
    source.write_text(
        "amcl:\n"
        "  ros__parameters:\n"
        "    base_frame_id: base_footprint\n"
        "controller_server:\n"
        "  ros__parameters:\n"
        "    controller_frequency: 20.0\n",
        encoding="utf-8",
    )
    destination = tmp_path / "derived.yaml"

    module.derive_nav2_params(source, "pinky_01", destination, root_key="pinky_01")

    document = yaml.safe_load(destination.read_text(encoding="utf-8"))
    assert set(document) == {"pinky_01"}
    assert (
        document["pinky_01"]["amcl"]["ros__parameters"]["base_frame_id"]
        == "pinky_01/base_footprint"
    )
    assert (
        document["pinky_01"]["controller_server"]["ros__parameters"][
            "controller_frequency"
        ]
        == 20.0
    )


def test_omitting_the_root_key_keeps_the_existing_flat_shape(tmp_path):
    """시뮬은 RewrittenYaml 이 감싸 주므로 기본값이 바뀌면 시뮬이 깨진다."""
    module = _module()
    source = tmp_path / "nav2_params.yaml"
    source.write_text(
        "amcl:\n  ros__parameters:\n    base_frame_id: base_footprint\n",
        encoding="utf-8",
    )
    destination = tmp_path / "derived.yaml"

    module.derive_nav2_params(source, "pinky_01", destination)

    document = yaml.safe_load(destination.read_text(encoding="utf-8"))
    assert "pinky_01" not in document
    assert document["amcl"]["ros__parameters"]["base_frame_id"] == "pinky_01/base_footprint"


def test_the_root_key_wraps_after_the_initial_pose_is_written(tmp_path):
    """초기 pose 를 심은 뒤에 감싸야 한다 — 순서가 뒤집히면 pose 가 밖에 남는다."""
    module = _module()
    source = tmp_path / "nav2_params.yaml"
    source.write_text("amcl:\n  ros__parameters:\n    alpha1: 0.2\n", encoding="utf-8")
    destination = tmp_path / "derived.yaml"

    module.derive_nav2_params(
        source,
        "pinky_01",
        destination,
        initial_pose=(1.5, -2.0, 0.25),
        root_key="pinky_01",
    )

    amcl = yaml.safe_load(destination.read_text(encoding="utf-8"))["pinky_01"]["amcl"]
    assert amcl["ros__parameters"]["set_initial_pose"] is True
    assert amcl["ros__parameters"]["initial_pose"] == {
        "x": 1.5,
        "y": -2.0,
        "z": 0.0,
        "yaw": 0.25,
    }


def test_the_local_costmap_odom_frame_is_namespaced(tmp_path):
    """`local_costmap.global_frame: odom` 이 맨 이름으로 남으면 로봇은 못 움직인다.

    URDF 가 프레임에 namespace 를 붙이므로 실제로 존재하는 것은 `pinky_01/odom`
    이다. costmap 이 맨 `odom` 을 찾으면 `Invalid frame ID "odom" ... frame does
    not exist` 로 변환을 영원히 기다리고, controller_server 가 경로를 따라갈 근거를
    잃는다. 2026-08-18 단일 로봇 시뮬에서 실제로 관측했다.
    """
    module = _module()
    source = tmp_path / "nav2_params.yaml"
    source.write_text(
        "local_costmap:\n"
        "  local_costmap:\n"
        "    ros__parameters:\n"
        "      global_frame: odom\n"
        "      robot_base_frame: base_footprint\n"
        "global_costmap:\n"
        "  global_costmap:\n"
        "    ros__parameters:\n"
        "      global_frame: map\n"
        "      robot_base_frame: base_footprint\n",
        encoding="utf-8",
    )
    destination = tmp_path / "derived.yaml"

    module.derive_nav2_params(source, "pinky_01", destination)

    document = yaml.safe_load(destination.read_text(encoding="utf-8"))
    local = document["local_costmap"]["local_costmap"]["ros__parameters"]
    world = document["global_costmap"]["global_costmap"]["ros__parameters"]
    assert local["global_frame"] == "pinky_01/odom"
    assert local["robot_base_frame"] == "pinky_01/base_footprint"
    # 지도는 두 로봇이 공유한다. 여기에 namespace 가 붙으면 서로 다른 지도를 믿는다.
    assert world["global_frame"] == "map"


def test_the_amcl_global_frame_id_stays_the_shared_map(tmp_path):
    module = _module()
    source = tmp_path / "nav2_params.yaml"
    source.write_text(
        "amcl:\n"
        "  ros__parameters:\n"
        "    global_frame_id: map\n"
        "    odom_frame_id: odom\n",
        encoding="utf-8",
    )
    destination = tmp_path / "derived.yaml"

    module.derive_nav2_params(source, "pinky_01", destination)

    amcl = yaml.safe_load(destination.read_text(encoding="utf-8"))["amcl"][
        "ros__parameters"
    ]
    assert amcl["global_frame_id"] == "map"
    assert amcl["odom_frame_id"] == "pinky_01/odom"


def test_every_frame_in_the_real_vendor_params_resolves_to_one_namespace(tmp_path):
    """실물 벤더 파일로 확인한다 — 맨 이름 프레임이 하나라도 남으면 안 된다."""
    module = _module()
    vendor = ROOT / "pinky_pro" / "pinky_navigation" / "params" / "nav2_params.yaml"
    if not vendor.is_file():
        pytest.skip("벤더 params 가 이 체크아웃에 없다")
    destination = tmp_path / "derived.yaml"

    module.derive_nav2_params(vendor, "pinky_01", destination)

    document = yaml.safe_load(destination.read_text(encoding="utf-8"))
    stray = []

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in module.FRAME_KEYS and isinstance(value, str):
                    if value != "map" and not value.startswith("pinky_01/"):
                        stray.append(f"{path}.{key} = {value}")
                else:
                    walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")

    walk(document)
    assert stray == []
