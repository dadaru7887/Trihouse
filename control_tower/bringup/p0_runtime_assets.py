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
3. Gazebo world 를 만든다. 발행된 world 는 이름만 있는 빈 SDF 라 바닥면조차
   없다. 바닥면 원본(`--world-source`)을 **읽기만 해서** 옮기고, 그 위에
   `--map-yaml` 의 점유 셀로 벽을 세운다. 벽을 손으로 만들지 않는 이유는
   `build_world_with_walls` 에 적었다 — Nav2 가 도는 지도와 물리가 갈라지면
   로봇이 "도착했다" 고 말하는 자리와 실제로 선 자리가 어긋난다.
4. 로봇마다 Nav2 파라미터를 파생한다. `pinky_pro` 원본은 프레임이
   `base_footprint`/`odom` 이고 costmap 이 `/scan` 을 절대 경로로 본다.
   두 대를 한 Gazebo 에 띄우면 서로 덮어쓰므로 namespace 를 입힌 사본을 만든다.

`pinky_pro` 아래의 파일은 어느 것도 고치지 않는다. 읽어서 파생본을 만들 뿐이다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
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
    # EN: Both charging bays must finish their local narrow-exit sequence before
    # entering the shared RMF graph. KO: 두 충전 베이는 로컬 협로 탈출을 끝낸 뒤
    # 공통 탈출점에서만 RMF 경로에 합류한다.
    ("TRIHOUSE-TEST-01-BOTTLENECK-01", "charging_station_narrow_exit"),
    ("charging_station_narrow_exit", "charging_station_01"),
    ("charging_station_narrow_exit", "charging_station_02"),
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
    # EN: Recovery behaviors also resolve odom through `local_frame`.
    # KO: Nav2 복구 동작도 `local_frame`으로 odom 프레임을 찾는다.
    "local_frame",
    # `local_costmap.global_frame` 이 `odom` 이다. 맨 이름으로 남으면 URDF 가 만든
    # `pinky_01/odom` 과 매칭되지 않아 costmap 이 `Invalid frame ID "odom" ...
    # frame does not exist` 로 변환을 영원히 기다리고, controller_server 가 경로를
    # 따라갈 근거를 잃는다. `global_costmap.global_frame` 은 `map` 이라 아래
    # rewrite 의 `map` 예외가 그대로 지켜 준다 — 두 로봇이 지도를 공유하기 때문이다.
    "global_frame",
    "global_frame_id",
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


def derive_simulation_narrow_zones(source: Path, destination: Path) -> None:
    """완성된 후보 협로 궤적을 P0에서만 왕복 검증할 수 있게 파생한다."""
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    for profile in (document.get("zones") or {}).values():
        if profile.get("approach_required", True) is False:
            continue
        complete = (
            profile.get("entry") is not None
            and profile.get("dock_target") is not None
            and bool(profile.get("enter"))
            and bool(profile.get("exit"))
            and profile.get("exit_target") is not None
        )
        if not complete:
            continue
        # EN: This derived file lives only under .trihouse/p0. It authorizes a
        # simulation round trip without claiming that physical exit was measured.
        # KO: 이 파생 파일은 .trihouse/p0에만 둔다. 실물 탈출 실측을 완료했다고
        # 주장하지 않으면서 시뮬레이션 왕복만 허용한다.
        measured = profile.setdefault("measured", {})
        measured.update(
            {"entry_pose": True, "dock_pose": True, "enter": True, "exit": True}
        )
        measured["simulation_override"] = True
    destination.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


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
    root_key: str | None = None,
) -> None:
    """한 로봇용 Nav2 파라미터를 만든다. 원본은 읽기만 한다.

    `initial_pose` 를 주면 AMCL 이 그 자리에서 위치추정을 시작한다. 공유 지도를
    쓰는 순간 이게 필수가 된다 — 초기 pose 가 없으면 AMCL 은 지도 전체에 입자를
    흩뿌린 채 시작하고, 두 로봇이 서로 다른 곳에 있다고 믿으면 RMF 의 교통
    조정이 근거를 잃는다. 로봇은 충전 스테이션에서 spawn 되므로 그 좌표가 곧
    참값이다.

    `root_key` 를 주면 문서 전체를 그 키 아래로 감싼다. `nav2_bringup` 은
    `RewrittenYaml(root_key=namespace)` 로 이것을 스스로 하지만, 벤더
    `pinky_navigation/launch/bringup_launch.xml` 은 `<param from>` 으로 원본을
    그대로 넘긴다. 그러면 `/pinky_01/amcl` 노드가 맨 키 `amcl:` 과 매칭되지
    않아 파라미터가 한 개도 적용되지 않는다.
    """
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    # 일부 벤더 복사본에는 BOM/오타처럼 보이는 접두사가 붙은 `지amcl:` 키가
    # 있었다. 그대로 두면 아래에서 만든 `amcl:`은 initial_pose만 가진 별도
    # 블록이 되고, 실제 AMCL은 scan/odom frame 설정을 하나도 못 받아 map->odom
    # TF를 내지 못한다. 원본은 수정하지 않고 런타임 파생본에서만 정규화한다.
    if isinstance(document, dict) and "amcl" not in document:
        malformed_amcl = [
            key for key in document
            if isinstance(key, str) and key.endswith("amcl") and key != "amcl"
        ]
        if len(malformed_amcl) == 1:
            document["amcl"] = document.pop(malformed_amcl[0])
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

    if root_key:
        # 초기 pose 를 심은 뒤에 감싼다. 순서가 뒤집히면 pose 가 감싼 문서 밖에 남는다.
        derived = {root_key: derived}

    destination.write_text(
        yaml.safe_dump(derived, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


# 벽 높이. 라이다 평면이 base_footprint 기준 0.125 m 다 — `pinky.urdf.xacro` 의
# base_link 0.028 + rplidar_mount 0.067 + rplidar_link 0.030. 벽이 그보다 낮으면
# 스캔이 그냥 지나가 벽이 없는 것과 같아진다.
WALL_HEIGHT_M = 0.30


@dataclass(frozen=True)
class MapGrid:
    """SLAM 지도를 격자로 읽은 것. `occupied` 는 (행, 열) 이고 행 0 이 위쪽이다."""

    width: int
    height: int
    resolution: float
    origin: tuple[float, float]
    occupied: frozenset[tuple[int, int]]


def _decode_image(data: bytes) -> tuple[int, int, list[int]]:
    """지도 이미지를 회색조 값으로 편다. **확장자가 아니라 magic bytes 로 고른다.**

    `new_map_2.pgm` 은 확장자만 `.pgm` 이고 내용은 PNG 다. 확장자로 파서를 고르면
    조용히 깨진 격자가 나오고, 그 격자로 세운 벽은 지도와 어긋난다.
    """
    if data.startswith(b"\x89PNG\r\n"):
        try:
            from PIL import Image  # 이 한 경우에만 필요하다
        except ImportError as error:  # pragma: no cover - 환경 문제
            raise SystemExit(
                "PNG 형식의 지도를 읽으려면 Pillow 가 필요합니다: pip install Pillow"
            ) from error
        import io

        image = Image.open(io.BytesIO(data)).convert("L")
        return image.width, image.height, list(image.getdata())

    if not data.startswith(b"P5"):
        raise SystemExit("지도 이미지가 P5 PGM 도 PNG 도 아닙니다")

    fields: list[int] = []
    offset = 2
    while len(fields) < 3:
        while offset < len(data) and data[offset : offset + 1].isspace():
            offset += 1
        if data[offset : offset + 1] == b"#":
            while offset < len(data) and data[offset : offset + 1] not in b"\r\n":
                offset += 1
            continue
        start = offset
        while offset < len(data) and not data[offset : offset + 1].isspace():
            offset += 1
        fields.append(int(data[start:offset]))
    offset += 1  # 헤더 마지막 공백 하나만 건너뛴다 (PGM 규약)
    width, height, _maximum = fields
    return width, height, list(data[offset : offset + width * height])


def read_map_grid(map_yaml: Path) -> MapGrid:
    """지도 yaml 과 이미지를 읽어 점유 셀을 고른다.

    판정은 ROS `map_server` 와 같다 — `negate` 를 반영한 뒤 점유 확률이
    `occupied_thresh` 를 넘는 셀만 점유다. **미확인 셀은 점유가 아니다.**
    대부분 방 밖이라 벽으로 세우면 없는 벽이 생긴다.
    """
    document = yaml.safe_load(map_yaml.read_text(encoding="utf-8"))
    image_path = (map_yaml.parent / document["image"]).resolve()
    width, height, pixels = _decode_image(image_path.read_bytes())

    negate = int(document.get("negate", 0))
    threshold = float(document.get("occupied_thresh", 0.65))
    origin = document["origin"]

    occupied = {
        (index // width, index % width)
        for index, value in enumerate(pixels)
        if (value / 255.0 if negate else (255 - value) / 255.0) > threshold
    }
    return MapGrid(
        width=width,
        height=height,
        resolution=float(document["resolution"]),
        origin=(float(origin[0]), float(origin[1])),
        occupied=frozenset(occupied),
    )


def _merge_rectangles(grid: MapGrid) -> list[tuple[int, int, int, int]]:
    """점유 셀을 겹치지 않는 직사각형으로 뭉친다. (행0, 열0, 행1, 열1) 을 돌려준다.

    셀 하나당 상자 하나로 두면 44 x 54 지도에서도 상자가 241 개다. Gazebo 의 접촉
    계산이 그만큼 늘고 RTF 가 떨어진다 — 12 코어 PC 에서는 그것만으로 충분히 아프다.
    가로로 최대한 늘린 뒤 같은 폭이 이어지는 동안 세로로 늘리는 탐욕 병합이면
    직교 벽으로 이루어진 이 지도에서 상자 수가 한 자릿수 배로 줄어든다.
    """
    remaining = set(grid.occupied)
    rectangles: list[tuple[int, int, int, int]] = []
    for row in range(grid.height):
        for column in range(grid.width):
            if (row, column) not in remaining:
                continue
            last_column = column
            while (row, last_column + 1) in remaining:
                last_column += 1
            last_row = row
            while all(
                (last_row + 1, spanned) in remaining
                for spanned in range(column, last_column + 1)
            ):
                last_row += 1
            for covered_row in range(row, last_row + 1):
                for covered_column in range(column, last_column + 1):
                    remaining.discard((covered_row, covered_column))
            rectangles.append((row, column, last_row, last_column))
    return rectangles


def build_world_with_walls(map_yaml: Path, world_source: Path, destination: Path) -> None:
    """원본 world 에 지도의 벽을 얹어 `destination` 에 쓴다. 원본은 읽기만 한다.

    벽을 손으로 만들지 않고 **Nav2 가 도는 것과 같은 yaml** 에서 만드는 이유는,
    손으로 만드는 순간 세 번째 진실이 생기기 때문이다 — 원장이 발행한 지도,
    Nav2 의 static layer, Gazebo 의 물리. 셋이 갈라지면 로봇이 "도착했다" 고 말하는
    자리와 실제로 선 자리가 어긋난다.
    """
    grid = read_map_grid(map_yaml)
    origin_x, origin_y = grid.origin
    resolution = grid.resolution

    links: list[str] = []
    for index, (row, column, last_row, last_column) in enumerate(_merge_rectangles(grid)):
        min_x = origin_x + column * resolution
        max_x = origin_x + (last_column + 1) * resolution
        min_y = origin_y + (grid.height - 1 - last_row) * resolution
        max_y = origin_y + (grid.height - row) * resolution
        links.append(
            f"""      <link name="wall_{index:04d}">
        <pose>{(min_x + max_x) / 2:.6f} {(min_y + max_y) / 2:.6f} """
            f"""{WALL_HEIGHT_M / 2:.6f} 0 0 0</pose>
        <collision name="collision">
          <geometry><box><size>{max_x - min_x:.6f} {max_y - min_y:.6f} """
            f"""{WALL_HEIGHT_M:.6f}</size></box></geometry>
        </collision>
        <visual name="visual">
          <geometry><box><size>{max_x - min_x:.6f} {max_y - min_y:.6f} """
            f"""{WALL_HEIGHT_M:.6f}</size></box></geometry>
          <material>
            <ambient>0.6 0.6 0.62 1</ambient>
            <diffuse>0.7 0.7 0.72 1</diffuse>
          </material>
        </visual>
      </link>"""
        )

    walls = (
        f"    <!-- {map_yaml.name} 에서 생성한 벽 {len(links)} 개. 손으로 고치지 않는다 -->\n"
        '    <model name="walls">\n'
        "      <static>true</static>\n"
        "      <pose>0 0 0 0 0 0</pose>\n" + "\n".join(links) + "\n    </model>\n"
    )

    source = world_source.read_text(encoding="utf-8")
    closing = source.rfind("</world>")
    if closing < 0:
        raise SystemExit(f"world 원본에 </world> 가 없습니다: {world_source}")
    destination.write_text(source[:closing] + walls + source[closing:], encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fms-base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--map-name", default="new_map_2")
    parser.add_argument("--map-revision", default="")
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--nav2-source", type=Path, required=True)
    parser.add_argument("--world-source", type=Path, required=True)
    parser.add_argument("--narrow-zones-source", type=Path, default=None)
    parser.add_argument(
        "--map-yaml",
        type=Path,
        default=None,
        help=(
            "Gazebo 에 벽을 세울 근거 지도. Nav2 가 도는 것과 같은 yaml 을 준다. "
            "SLAM 모드처럼 지도가 없으면 생략하고, 그러면 바닥면만 있는 world 가 된다"
        ),
    )
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
    if args.map_yaml is None:
        # SLAM 모드에는 세울 근거가 없다. 바닥면만 있는 world 로 둔다.
        world_path.write_text(args.world_source.read_text(encoding="utf-8"), encoding="utf-8")
        print("[assets] 지도가 없어 벽을 세우지 않습니다 (바닥면만)")
    else:
        build_world_with_walls(args.map_yaml, args.world_source, world_path)
        grid = read_map_grid(args.map_yaml)
        print(
            f"[assets] {args.map_yaml.name} 의 점유 셀 {len(grid.occupied)} 개로 벽을 세웠습니다"
        )

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

    narrow_zones_path: Path | None = None
    if args.narrow_zones_source is not None:
        narrow_zones_path = output / "narrow_zones.yaml"
        derive_simulation_narrow_zones(args.narrow_zones_source, narrow_zones_path)

    summary = {
        "map_revision": published["map_revision"],
        "nav_graph": str(nav_graph_path),
        "world": str(world_path),
        "published_dir": str(published_dir),
        "nav2_params": nav2_files,
        "narrow_zones": str(narrow_zones_path) if narrow_zones_path else None,
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
