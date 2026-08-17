"""발행된 지도 revision 을 호스트 ROS 층이 쓸 수 있는 파일로 펼친다.

Gateway 는 발행된 지도를 **내용**으로만 준다(`/internal/v1/maps/<name>/published`).
반면 `two_pinky_order_demo.launch.py` 는 `nav_graph`, `world`,
`nav2_params_file` 을 **파일 경로**로 받는다. 그 사이를 잇는 것이 이 스크립트다.

하는 일:

1. 발행된 지도를 받아 `TRIHOUSE_MAP_REVISION` 과 같은 revision 인지, 각
   아티팩트의 sha256 이 맞는지 확인하고 그대로 기록해 둔다(출처 보존).
2. RMF navigation graph 를 만든다. 발행된 nav graph 는 정점만 있고
   `lanes: []` 라 RMF 가 경로를 못 만든다. 승인된 JSONL 의 병목 두 곳을
   정점으로 추가하고, 실측 배치가 말하는 통로대로 lane 을 잇는다.
3. Gazebo world 를 고른다. 발행된 world 는 이름만 있는 빈 SDF 라 바닥면조차
   없다. `pinky_gz_sim` 의 `empty.world` 를 **읽기만 해서** 복사한다.
4. 로봇마다 Nav2 파라미터를 파생한다. `pinky_pro` 원본은 프레임이
   `base_footprint`/`odom` 이고 costmap 이 `/scan` 을 절대 경로로 본다.
   두 대를 한 Gazebo 에 띄우면 서로 덮어쓰므로 namespace 를 입힌 사본을 만든다.

`pinky_pro` 아래의 파일은 어느 것도 고치지 않는다. 읽어서 파생본을 만들 뿐이다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml


# 승인된 JSONL 의 실측 배치가 말하는 통로. 오른쪽 창고 열(적재 Dock 3곳)에서
# 왼쪽 포장/충전 열로 가려면 반드시 병목 01 을 지난다. 포장대와 안전구역은
# 병목 02 뒤에 있다. 두 로봇이 같은 통로를 요구하면 여기서 경합이 생긴다.
LANE_TOPOLOGY: tuple[tuple[str, str], ...] = (
    ("ambient_storage_loading_dock_01", "TRIHOUSE-TEST-01-BOTTLENECK-01"),
    ("chilled_storage_loading_dock_01", "TRIHOUSE-TEST-01-BOTTLENECK-01"),
    ("frozen_storage_loading_dock_01", "TRIHOUSE-TEST-01-BOTTLENECK-01"),
    ("TRIHOUSE-TEST-01-BOTTLENECK-01", "TRIHOUSE-TEST-01-BOTTLENECK-02"),
    ("TRIHOUSE-TEST-01-BOTTLENECK-01", "charging_station_01"),
    ("TRIHOUSE-TEST-01-BOTTLENECK-01", "charging_station_02"),
    ("TRIHOUSE-TEST-01-BOTTLENECK-02", "packing_station_loading_dock_01"),
    ("TRIHOUSE-TEST-01-BOTTLENECK-02", "packing_station_loading_dock_02"),
    ("TRIHOUSE-TEST-01-BOTTLENECK-02", "safety_zone_01"),
)

# Nav2 파라미터에서 로봇마다 갈라져야 하는 프레임 이름.
#
# `base_frame` 과 `fixed_frame` 은 docking_server 가 쓰는 이름이다. 같은 뜻의 키를
# 노드마다 다르게 부르므로 둘 다 적어 둔다.
FRAME_KEYS = (
    "base_frame_id",
    "odom_frame_id",
    "robot_base_frame",
    "base_frame",
    "fixed_frame",
)

# 절대 경로로 적혀 있어 두 로봇이 서로의 것을 보게 되는 토픽.
ABSOLUTE_TOPIC_KEYS = ("topic", "scan_topic", "odom_topic")

# 벤더 params 에 없어서 우리가 채워야 하는 collision_monitor 설정.
#
# `nav2_bringup/launch/navigation_launch.py` 는 controller_server 와
# velocity_smoother 와 behavior_server 의 `cmd_vel` 을 모두 `cmd_vel_nav` 로
# remap 하고 collision_monitor 에만 remap 을 걸지 않는다. 그래서 `cmd_vel` 을
# 발행하는 노드는 collision_monitor 하나뿐이고, 그것이 Gazebo bridge 가 듣는
# 토픽이다. 이 노드는 `lifecycle_nodes` 에 무조건 들어 있는데 `observation_sources`
# 에 기본값이 없어서, 절이 비어 있으면 configure 에서 죽고 navigation lifecycle
# 전체가 그 자리에서 멈춘다. 곧 이 절이 없으면 로봇은 한 발도 움직이지 못한다.
#
# 값은 `nav2_bringup/params/nav2_params.yaml` 의 기본값을 그대로 따른다. 토픽과
# 프레임은 상대 이름으로 두어 아래 `rewrite` 가 로봇마다 갈라 준다.
#
# 폴리곤은 nav2 기본값이다. 실물 Pinky 의 정지거리로 검증된 값이 아니므로 실기
# 배포 전에 `time_before_collision` 과 `min_points` 를 실측으로 다시 잡아야 한다.
COLLISION_MONITOR_DEFAULTS: dict[str, Any] = {
    "ros__parameters": {
        "base_frame_id": "base_footprint",
        "odom_frame_id": "odom",
        "cmd_vel_in_topic": "cmd_vel_smoothed",
        "cmd_vel_out_topic": "cmd_vel",
        "state_topic": "collision_monitor_state",
        "transform_tolerance": 0.2,
        "source_timeout": 1.0,
        "base_shift_correction": True,
        "stop_pub_timeout": 2.0,
        "polygons": ["FootprintApproach"],
        "FootprintApproach": {
            "type": "polygon",
            "action_type": "approach",
            # 상대 이름이라 `/<namespace>/local_costmap/published_footprint` 로
            # 풀린다. 벤더도 behavior_server 에서 같은 형태를 쓴다.
            "footprint_topic": "local_costmap/published_footprint",
            "time_before_collision": 1.2,
            "simulation_time_step": 0.1,
            "min_points": 6,
            "visualize": False,
            "enabled": True,
        },
        "observation_sources": ["scan"],
        "scan": {
            "type": "scan",
            # `topic` 은 ABSOLUTE_TOPIC_KEYS 라서 로봇 namespace 가 붙는다.
            # 붙지 않으면 두 로봇이 서로의 스캔을 보고 서로를 장애물로 여긴다.
            "topic": "scan",
            "min_height": 0.15,
            "max_height": 2.0,
            "enabled": True,
        },
    }
}

# 벤더 params 에 없어서 우리가 채워야 하는 docking_server 설정.
#
# P0 는 도킹을 쓰지 않는다. 충전은 RMF 가 충전기 waypoint 로 관리한다. 그런데
# `docking_server` 는 navigation `lifecycle_nodes` 의 마지막 항목이고 목록에 무조건
# 들어 있어서, `dock_plugins` 가 없으면 `Charging dock plugins not given!` 로
# configure 에 실패한다. lifecycle_manager 는 그 하나 때문에 navigation 전체를
# abort 하므로, 앞의 노드가 다 정상이어도 로봇은 뜨지 않는다.
#
# 그래서 여기서 하려는 것은 도킹을 켜는 것이 아니라 노드가 configure 를 통과해
# 조용히 대기하게 만드는 것이다. dock 인스턴스(`docks`)는 두지 않는다 — 두면
# 쓰지도 않는 기능이 설정된 것처럼 보인다. 외부 검출 pose 도 끈다. 그것은 aruco
# 파이프라인을 전제하는데 P0 에는 없고, 켜 두면 오지 않는 검출을 기다린다.
DOCKING_SERVER_DEFAULTS: dict[str, Any] = {
    "ros__parameters": {
        "controller_frequency": 50.0,
        "base_frame": "base_link",
        "fixed_frame": "odom",
        "dock_plugins": ["simple_charging_dock"],
        "simple_charging_dock": {
            "plugin": "opennav_docking::SimpleChargingDock",
            "docking_threshold": 0.05,
            "staging_x_offset": -0.7,
            "use_external_detection_pose": False,
            "use_battery_status": False,
            "use_stall_detection": False,
        },
    }
}


def fetch_published(fms_base_url: str, map_name: str) -> dict[str, Any]:
    url = f"{fms_base_url.rstrip('/')}/internal/v1/maps/{map_name}/published"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise SystemExit(
            f"발행된 지도를 받지 못했습니다 ({error.code}): {url}\n"
            "먼저 관제 UI 의 지도 화면에서 저장 -> 검증 -> 배포를 하세요."
        ) from error
    except urllib.error.URLError as error:
        raise SystemExit(f"Gateway 에 연결하지 못했습니다: {url} ({error.reason})") from error


def verify(published: dict[str, Any], expected_revision: str) -> dict[str, str]:
    """revision 과 아티팩트 해시가 발행된 것과 같은지 확인하고 내용을 돌려준다."""
    actual = published.get("map_revision")
    if expected_revision and actual != expected_revision:
        raise SystemExit(
            "발행된 지도 revision 이 요청과 다릅니다.\n"
            f"  요청: {expected_revision}\n  발행: {actual}"
        )
    artifacts = published["manifest"]["artifacts"]
    contents: dict[str, str] = {}
    for name, artifact in artifacts.items():
        content = artifact["content"]
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if digest != artifact["sha256"]:
            raise SystemExit(f"{name} 의 sha256 이 맞지 않습니다: {digest} != {artifact['sha256']}")
        contents[name] = content
    return contents


# 로봇별 고정 충전기. `control_tower/task_manager/assignment.py` 의
# CHARGER_BY_MOBILE 과 같은 값이고, Gateway 도 이 쌍이 아니면 배정을 거절한다
# (FIXED_CHARGER_MISMATCH). 로봇은 여기서 spawn 되므로 AMCL 초기 pose 도 같다.
CHARGER_BY_ROBOT = {
    "PK_01": "TRIHOUSE-TEST-01-CHG-01",
    "PK_02": "TRIHOUSE-TEST-01-CHG-02",
}


def charger_pose(
    waypoints: dict[str, dict], robot_id: str
) -> tuple[float, float, float] | None:
    """로봇의 고정 충전기 좌표를 승인된 JSONL 에서만 읽는다."""
    charger_code = CHARGER_BY_ROBOT.get(robot_id)
    if charger_code is None:
        return None
    for record in waypoints.values():
        if record.get("location_code") != charger_code:
            continue
        pose = record.get("map_pose") or {}
        return (
            float(pose["x"]),
            float(pose["y"]),
            float(pose.get("yaw") or 0.0),
        )
    raise SystemExit(
        f"승인된 JSONL 에 {robot_id} 의 충전기 {charger_code} 가 없습니다"
    )


def load_features(features_path: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """승인된 JSONL 에서 waypoint 와 병목을 읽는다. 좌표는 여기서만 온다."""
    waypoints: dict[str, dict] = {}
    bottlenecks: dict[str, dict] = {}
    for line in features_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("record_type") == "waypoint":
            waypoints[record["rmf_waypoint_name"]] = record
        elif record.get("record_type") == "bottleneck":
            bottlenecks[record["feature_code"]] = record
    return waypoints, bottlenecks


def build_nav_graph(
    map_name: str,
    waypoints: dict[str, dict],
    bottlenecks: dict[str, dict],
) -> str:
    """정점과 lane 을 갖춘 RMF navigation graph 를 만든다.

    발행된 graph 는 `lanes: []` 라 RMF 가 어떤 경로도 계획하지 못한다. 좌표는
    승인된 JSONL 에서만 읽고, 연결은 LANE_TOPOLOGY 가 정한다.
    """
    vertices: list[list[Any]] = []
    index: dict[str, int] = {}

    for name in sorted(waypoints):
        record = waypoints[name]
        pose = record["map_pose"]
        properties: dict[str, Any] = {"name": name}
        if record.get("operational_role") == "charging_station":
            properties["is_charger"] = True
            properties["is_parking_spot"] = True
        elif record.get("operational_role") == "loading_dock":
            properties["is_holding_point"] = True
        index[name] = len(vertices)
        vertices.append([float(pose["x"]), float(pose["y"]), properties])

    for code in sorted(bottlenecks):
        record = bottlenecks[code]
        pose = record["map_pose"]
        index[code] = len(vertices)
        vertices.append([
            float(pose["x"]),
            float(pose["y"]),
            # 병목은 상호배제 구역이다. 먼저 진입한 로봇이 통과할 때까지 다른
            # 로봇은 기다린다. 좌표와 mutex_group 모두 승인된 JSONL 값이다.
            {"name": code, "mutex_group": record["mutex_group"]},
        ])

    lanes: list[list[Any]] = []
    for start, end in LANE_TOPOLOGY:
        for missing in (start, end):
            if missing not in index:
                raise SystemExit(f"lane 이 가리키는 지점이 승인된 JSONL 에 없습니다: {missing}")
        # 양방향. RMF 는 방향마다 lane 을 하나씩 요구한다.
        lanes.append([index[start], index[end], {}])
        lanes.append([index[end], index[start], {}])

    return yaml.safe_dump(
        {"building_name": map_name, "levels": {"L1": {"vertices": vertices, "lanes": lanes}}},
        allow_unicode=True,
        sort_keys=True,
    )


def derive_nav2_params(
    source: Path,
    namespace: str,
    destination: Path,
    *,
    initial_pose: tuple[float, float, float] | None = None,
) -> None:
    """한 로봇용 Nav2 파라미터를 만든다. 원본은 읽기만 한다.

    `initial_pose` 를 주면 AMCL 이 그 자리에서 위치추정을 시작한다. 공유 지도를
    쓰는 순간 이게 필수가 된다 — 초기 pose 가 없으면 AMCL 은 지도 전체에 입자를
    흩뿌린 채 시작하고, 두 로봇이 서로 다른 곳에 있다고 믿으면 RMF 의 교통
    조정이 근거를 잃는다. 로봇은 충전 스테이션에서 spawn 되므로 그 좌표가 곧
    참값이다.
    """
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    # 벤더가 이 절을 채우면 그것을 그대로 쓴다. 우리 기본값은 빈 자리만 메운다.
    document.setdefault("collision_monitor", COLLISION_MONITOR_DEFAULTS)
    document.setdefault("docking_server", DOCKING_SERVER_DEFAULTS)

    def rewrite(node: Any) -> Any:
        if isinstance(node, dict):
            result = {}
            for key, value in node.items():
                if key in FRAME_KEYS and isinstance(value, str):
                    # URDF 가 프레임에 namespace 를 붙이므로 Nav2 도 같은 이름을
                    # 봐야 한다. map 은 두 로봇이 공유하니 그대로 둔다.
                    result[key] = value if value == "map" else f"{namespace}/{value}"
                elif key in ABSOLUTE_TOPIC_KEYS and isinstance(value, str):
                    result[key] = f"/{namespace}/{value.lstrip('/')}"
                else:
                    result[key] = rewrite(value)
            return result
        if isinstance(node, list):
            return [rewrite(item) for item in node]
        return node

    derived = rewrite(document)
    if initial_pose is not None:
        x, y, yaw = initial_pose
        amcl = derived.setdefault("amcl", {}).setdefault("ros__parameters", {})
        amcl["set_initial_pose"] = True
        # nav2_amcl 은 `initial_pose.x` 처럼 개별 파라미터를 선언한다. 원본의
        # `initial_pose: [0, 0, 0]` 리스트 형태는 어떤 파라미터에도 매칭되지
        # 않아 조용히 무시된다. 중첩 매핑으로 바꿔 써야 실제로 반영된다.
        amcl["initial_pose"] = {"x": float(x), "y": float(y), "z": 0.0, "yaw": float(yaw)}

    destination.write_text(
        yaml.safe_dump(derived, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fms-base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--map-name", default="trihouse_test_01")
    parser.add_argument("--map-revision", default="")
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--nav2-source", type=Path, required=True)
    parser.add_argument("--world-source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--robot",
        action="append",
        default=[],
        metavar="ROBOT_ID:NAMESPACE",
        help="Nav2 파라미터를 파생할 로봇. 예: PK_01:pinky_01",
    )
    args = parser.parse_args(argv)

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)

    published = fetch_published(args.fms_base_url, args.map_name)
    contents = verify(published, args.map_revision)

    # 발행본 자체를 그대로 남긴다. 무엇을 근거로 띄웠는지 나중에 대조할 수 있다.
    published_dir = output / "published"
    published_dir.mkdir(exist_ok=True)
    (published_dir / "building.yaml").write_text(contents["building_yaml"], encoding="utf-8")
    (published_dir / "nav_graph.yaml").write_text(contents["nav_graph_yaml"], encoding="utf-8")
    (published_dir / "world.sdf").write_text(contents["world_sdf"], encoding="utf-8")
    (published_dir / "manifest.json").write_text(
        json.dumps(published["manifest"], ensure_ascii=False, indent=2), encoding="utf-8"
    )

    waypoints, bottlenecks = load_features(args.features)
    nav_graph_path = output / "nav_graph.yaml"
    nav_graph_path.write_text(
        build_nav_graph(args.map_name, waypoints, bottlenecks), encoding="utf-8"
    )

    world_path = output / "world.sdf"
    shutil.copyfile(args.world_source, world_path)

    nav2_dir = output / "nav2"
    nav2_dir.mkdir(exist_ok=True)
    nav2_files: dict[str, str] = {}
    for entry in args.robot:
        robot_id, _, namespace = entry.partition(":")
        if not namespace:
            raise SystemExit(f"--robot 는 ROBOT_ID:NAMESPACE 형식입니다: {entry}")
        destination = nav2_dir / f"{namespace}.yaml"
        derive_nav2_params(
            args.nav2_source,
            namespace,
            destination,
            initial_pose=charger_pose(waypoints, robot_id),
        )
        nav2_files[robot_id] = str(destination)

    summary = {
        "map_revision": published["map_revision"],
        "nav_graph": str(nav_graph_path),
        "world": str(world_path),
        "published_dir": str(published_dir),
        "nav2_params": nav2_files,
        "vertices": len(waypoints) + len(bottlenecks),
        "lanes": len(LANE_TOPOLOGY) * 2,
    }
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
    print()
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
