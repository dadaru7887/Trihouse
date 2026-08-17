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
