"""RMF core 하나와 격리된 두 Pinky namespace로 P0 주문 시연을 띄운다.

`PK_01/pinky_01`과 `PK_02/pinky_02`는 스캔·odom·pose·경로 계산·경로 추종·
지역/전역 경로·costmap·상태 토픽을 모두 namespace 아래에서만 주고받는다.
두 로봇의 spawn pose는 승인된 physical-feature JSONL의 충전 스테이션
기록에서만 읽는다. 좌표를 launch 파일에 새로 적지 않는다.

내부 bootstrap graph는 등록된 로봇·충전기·Waypoint에 대해서만 생성되며
운영자 편집 레이어가 아니다.
"""

import os
import re
from pathlib import Path

import xacro
from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    GroupAction,
    IncludeLaunchDescription,
    OpaqueFunction,
    SetEnvironmentVariable,
    TimerAction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import (
    EnvironmentVariable,
    LaunchConfiguration,
    PathJoinSubstitution,
)
from launch_ros.actions import Node, PushRosNamespace, SetRemap
from launch_ros.parameter_descriptions import ParameterValue


# Control Tower가 고정한 Pinky <-> 충전기 결속. 이 표는 운영 정책이며
# 좌표는 항상 승인된 JSONL에서 읽는다.
ROBOT_CHARGERS = (
    ("PK_01", "pinky_01", "TRIHOUSE-TEST-01-CHG-01"),
    ("PK_02", "pinky_02", "TRIHOUSE-TEST-01-CHG-02"),
)


def selected_robots(context) -> tuple[tuple[str, str, str], ...]:
    """`robots:=PK_01` 로 고른 로봇만 낸다. 비어 있으면 전부.

    로봇 두 대의 전체 스택(Gazebo + Nav2 두 벌 + Open-RMF + 로봇당 온보드 노드
    여섯 개)은 개발 PC 한 대의 용량을 넘는다. 부하가 높으면 Nav2 의 lifecycle
    manager 가 `map_server/get_state` 를 기다리다 포기하고 새로 붙는 노드도 토픽을
    발견하지 못한다. 설정 결함이 아니라 부하이므로, 주문 경로를 증명할 때는 로봇을
    한 대로 줄여 변수를 없애는 편이 빠르다.

    두 대 구성을 없애지는 않는다. 교통 조정과 병목 예약은 두 대가 있어야 의미가 있다.
    """
    requested = LaunchConfiguration("robots").perform(context).strip()
    if not requested:
        return ROBOT_CHARGERS

    wanted = [token.strip() for token in requested.split(",") if token.strip()]
    known = {entry[0] for entry in ROBOT_CHARGERS}
    unknown = [name for name in wanted if name not in known]
    if unknown:
        # 오타가 조용히 "로봇 0대" 로 끝나면 무엇이 잘못됐는지 알 수 없다.
        raise RuntimeError(
            f"모르는 robot id 입니다: {', '.join(unknown)}. "
            f"고를 수 있는 것: {', '.join(sorted(known))}"
        )

    return tuple(entry for entry in ROBOT_CHARGERS if entry[0] in wanted)

# 각 로봇 namespace 안에서만 유지되어야 하는 토픽/action 이름.
NAMESPACED_INTERFACES = (
    "scan",
    "odom",
    "amcl_pose",
    "compute_path_to_pose",
    "follow_path",
    "plan",
    "local_plan",
    "global_costmap/costmap",
    "local_costmap/costmap",
    "trihouse/status",
)


# Gazebo <-> ROS 로 넘겨야 하는 로봇별 토픽. gz 쪽 이름은 URDF 가
# `namespace:=pinky_01/` 로 이미 갈라 놓았으므로 여기서도 같은 접두사를 쓴다.
# `[` 는 gz -> ROS, `]` 는 ROS -> gz 다.
ROBOT_BRIDGE_TOPICS = (
    "cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist",
    "odom@nav_msgs/msg/Odometry[gz.msgs.Odometry",
    "scan@sensor_msgs/msg/LaserScan[gz.msgs.LaserScan",
    "joint_states@sensor_msgs/msg/JointState[gz.msgs.Model",
    "imu_raw@sensor_msgs/msg/Imu[gz.msgs.IMU",
)

# 두 로봇이 공유하는 토픽. `/clock` 은 use_sim_time 의 근거이고, TF 는 URDF 가
# 프레임마다 namespace 를 붙여 두어 한 트리에 같이 있어도 섞이지 않는다.
WORLD_BRIDGE_TOPICS = (
    "/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock",
    "/tf@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V",
)


def _enabled(context, name: str) -> bool:
    return LaunchConfiguration(name).perform(context).strip().lower() in {
        "1", "true", "yes", "on",
    }


def _imported_features(features_path: Path):
    """승인된 JSONL을 읽는다. 좌표와 이름은 언제나 여기서만 온다."""
    import sys

    repository_root = Path(__file__).resolve().parents[2]
    if str(repository_root) not in sys.path:
        sys.path.insert(0, str(repository_root))
    from fms_gateway.app.physical_features import PhysicalFeatureImporter

    return PhysicalFeatureImporter().parse(features_path)


def _charger_waypoint(imported, charger_code: str):
    waypoint = imported.waypoint(charger_code)
    if waypoint.operational_role != "charging_station":
        raise RuntimeError(
            f"{charger_code}는 charging_station이 아닙니다: "
            f"{waypoint.operational_role}"
        )
    return waypoint


def charger_spawn_poses(features_path: Path) -> dict[str, tuple[float, float, float]]:
    """승인된 JSONL의 충전 스테이션 pose만 로봇별로 돌려준다."""
    imported = _imported_features(features_path)
    poses: dict[str, tuple[float, float, float]] = {}
    for robot_id, _namespace, charger_code in ROBOT_CHARGERS:
        waypoint = _charger_waypoint(imported, charger_code)
        if waypoint.pose.yaw is None:
            raise RuntimeError(f"{charger_code}에 측정된 yaw가 없습니다")
        poses[robot_id] = (waypoint.pose.x, waypoint.pose.y, waypoint.pose.yaw)
    return poses


def charger_graph_names(features_path: Path) -> dict[str, str]:
    """충전기를 nav_graph 가 실제로 쓰는 이름으로 돌려준다.

    `build_nav_graph` 는 waypoint 정점을 `rmf_waypoint_name`(`charging_station_01`)
    으로 이름 짓는다. adapter 에 `location_code`(`TRIHOUSE-TEST-01-CHG-01`)를 주면
    이렇게 찍고 로봇을 fleet 에 넣지 않는다.

      Cannot find a waypoint named [TRIHOUSE-TEST-01-CHG-01] in the navigation
      graph of fleet [project1_pinky] ... We will not add the robot to the fleet

    로봇이 fleet 에 없으면 낙찰이 나지 않아 주문이 로봇까지 가지 못한다. 두 이름을
    손으로 맞추지 않고 graph 를 만든 것과 같은 JSONL 에서 읽어 갈라지지 않게 한다.
    """
    imported = _imported_features(features_path)
    return {
        robot_id: _charger_waypoint(imported, charger_code).rmf_waypoint_name
        for robot_id, _namespace, charger_code in ROBOT_CHARGERS
    }


def _robot_description(namespace: str) -> str:
    """xacro 를 펼치고 `<gazebo reference>` 의 링크 접두사만 벗긴다.

    `pinky.urdf.xacro` 는 joint 이름에만 `${namespace}` 를 붙이고 link 이름에는
    붙이지 않는다. 그런데 `pinky_gz.urdf.xacro` 는 링크를
    `${namespace}rplidar_link` 로 참조한다. 가리키는 링크가 없으므로 sdformat 이
    URDF 를 SDF 로 바꿀 때 그 `<gazebo>` 블록을 **조용히 버린다** — 오류도 경고도
    없다. 그 결과 라이다·IMU·카메라가 Gazebo 에 아예 생기지 않고, 바퀴 마찰
    설정도 사라진다. 스캔이 없으면 AMCL 이 map->odom 을 내지 못하고, `map`
    프레임이 없어 global_costmap 이 활성화에 실패하며, planner_server 가 죽어
    Nav2 navigation lifecycle 전체가 중단된다.

    `pinky_pro` 는 고정된 서브모듈이자 읽기 전용 자산이므로 원본을 고치지 않고
    펼친 결과에서만 되돌린다. **링크를 가리키는 참조만** 벗긴다 —
    `robot_lamp_mount_fixed_joint` 처럼 joint 를 가리키는 참조는 접두사가 붙어
    있는 것이 맞으므로 그대로 둔다.
    """
    source = (
        Path(get_package_share_directory("pinky_description"))
        / "urdf"
        / "robot.urdf.xacro"
    )
    document = xacro.process_file(
        str(source), mappings={"namespace": f"{namespace}/", "is_sim": "True"}
    )
    description = document.toxml()
    link_names = set(re.findall(r'<link name="([^"]+)"', description))

    def _strip(match: "re.Match[str]") -> str:
        target = match.group(1)
        bare = target[len(namespace) + 1 :]
        if target.startswith(f"{namespace}/") and bare in link_names:
            return f'<gazebo reference="{bare}"'
        return match.group(0)

    return re.sub(r'<gazebo reference="([^"]+)"', _strip, description)


def _robot_group(
    context,
    *,
    robot_id: str,
    namespace: str,
    charger_code: str,
    spawn_pose: tuple[float, float, float],
    nav_graph: Path,
) -> GroupAction:
    """한 Pinky의 Gazebo spawn, Nav2 스택, adapter를 namespace 안에 가둔다."""
    use_sim_time = LaunchConfiguration("use_sim_time")
    map_revision = LaunchConfiguration("map_revision")
    # 로봇마다 프레임과 토픽을 갈라 둔 파생 파라미터가 있으면 그것을 쓴다.
    # 없으면 원본으로 돌아간다 — 다만 두 대를 함께 띄우면 서로의 costmap 과
    # odom 을 보게 되므로 파생본이 정상 경로다.
    nav2_params = Path(
        LaunchConfiguration("nav2_params_file").perform(context)
    ).expanduser().resolve()
    params_dir = LaunchConfiguration("nav2_params_dir").perform(context).strip()
    if params_dir:
        derived = Path(params_dir).expanduser().resolve() / f"{namespace}.yaml"
        if derived.is_file():
            nav2_params = derived
    x, y, yaw = spawn_pose

    # 협로 존 표는 지도마다 다르다. Nav2 지도 파일 이름에서 표 이름을 만들고, 없으면
    # 빈 문자열을 넘겨 규칙 주행을 끈다(지금까지처럼 Nav2 가 끝까지 간다).
    nav2_map = Path(LaunchConfiguration("nav2_map").perform(context)).expanduser()
    narrow_map_name = nav2_map.stem if nav2_map.name else ""
    zones_path = (
        Path(get_package_share_directory("trihouse_rmf_bridge")).parents[2]
        / "config" / f"narrow_zones.{narrow_map_name}.yaml"
    )
    repository_zones = Path(__file__).resolve().parents[2] / "config" / f"narrow_zones.{narrow_map_name}.yaml"
    narrow_zones_file = str(
        zones_path if zones_path.is_file() else repository_zones
        if repository_zones.is_file() else ""
    )
    # 표가 없으면 규칙 주행이 통째로 꺼진다. 조용히 꺼지면 운영자는 로봇이 협로에서
    # 헤매는 것을 Nav2 탓으로 오해한다. 어느 파일을 찾았는지까지 밝힌다.
    if not narrow_zones_file:
        print(
            f"[협로] 지도 '{narrow_map_name}' 의 존 표가 없어 규칙 주행을 끕니다. "
            f"찾은 자리: {repository_zones}",
            flush=True,
        )

    actions = [
        PushRosNamespace(namespace),
        # Gazebo 는 `robot_description` 토픽을 읽어 모델을 만든다. 이걸 내보내는
        # 것이 robot_state_publisher 다. `pinky_description` 의 xacro 를 읽기만
        # 해서 namespace 를 입힌다 — pinky_pro 아래 파일은 고치지 않는다.
        # joint_state_publisher 는 띄우지 않는다. joint_states 는 Gazebo 가
        # 내보내고 bridge 가 넘겨 주므로, 함께 띄우면 서로를 되먹인다.
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            name="robot_state_publisher",
            output="screen",
            parameters=[{
                "use_sim_time": use_sim_time,
                "frame_prefix": f"{namespace}/",
                "robot_description": ParameterValue(
                    _robot_description(namespace), value_type=str
                ),
            }],
            # nav2 는 TF 를 전역 `/tf` 에서 읽지 않는다. `nav2_bringup` 이 모든
            # 노드에 `[('/tf','tf'), ('/tf_static','tf_static')]` 을 무조건 걸어
            # 두어서, 바깥 PushRosNamespace 가 접두사를 붙인 `/pinky_01/tf` 와
            # `/pinky_01/tf_static` 을 듣는다. 발행자가 전역에만 쓰면 nav2 의 TF
            # 버퍼는 비어 있고, AMCL 은 스캔마다 변환을 찾지 못해 전량 폐기한다
            # (`Message Filter dropping message`). 그러면 위치추정이 한 번도 돌지
            # 않아 `amcl_pose` 가 없고, status 의 frame_id 가 `map` 이 되지 못해
            # RMF adapter 가 로봇을 거부한다.
            #
            # 프레임 이름에는 위의 `frame_prefix` 가 이미 namespace 를 붙여 두었다.
            # 그래서 트리를 로봇 namespace 안에서 주고받아도 두 로봇이 섞이지 않는다.
            remappings=[("/tf", "tf"), ("/tf_static", "tf_static")],
        ),
        Node(
            package="ros_gz_sim",
            executable="create",
            name="spawn_pinky",
            output="screen",
            arguments=[
                "-name", namespace,
                "-topic", "robot_description",
                "-x", f"{x:.6f}",
                "-y", f"{y:.6f}",
                # 바닥을 뚫고 생성되지 않도록 살짝 띄운다.
                "-z", "0.05",
                "-Y", f"{yaw:.6f}",
            ],
        ),
        IncludeLaunchDescription(
            AnyLaunchDescriptionSource(
                str(Path(__file__).with_name("pinky_easy_fleet_adapter.launch.py"))
            ),
            launch_arguments={
                "config_file": LaunchConfiguration("fleet_config"),
                "nav_graph": str(nav_graph),
                "robot_name": robot_id,
                "rmf_map_name": LaunchConfiguration("rmf_map_name"),
                "charger_waypoint": charger_code,
                "map_revision": map_revision,
                "fms_base_url": LaunchConfiguration("fms_base_url"),
                "robot_status_topic": f"/{namespace}/trihouse/status",
                "transport_action": f"/{namespace}/trihouse/transport/execute",
                "use_sim_time": use_sim_time,
            }.items(),
        ),
        # `bringup_launch.py` 는 실행 파일이 아니라 launch 파일이다. Node 로
        # 띄우면 "executable not found" 로 죽는다. 반드시 include 해야 한다.
        # 파라미터는 로봇마다 프레임/토픽을 갈라 둔 파생본을 쓴다
        # (control_tower/bringup/p0_runtime_assets.py).
        # upstream Nav2의 collision_monitor와 docking_server도 기본값으로
        # `cmd_vel`을 발행한다. Nav2 include 전체에만 remap을 걸어 모든 주행
        # 후보를 `cmd_vel_nav`로 모으고, 아래 safety supervisor만 실제
        # `cmd_vel`을 소유하게 한다.
        GroupAction([
            SetRemap(src="cmd_vel", dst="cmd_vel_nav"),
            IncludeLaunchDescription(
                AnyLaunchDescriptionSource(
                    str(
                        Path(get_package_share_directory("nav2_bringup"))
                        / "launch"
                        / "bringup_launch.py"
                    )
                ),
                launch_arguments={
                # `namespace` 는 두 가지를 정하는데 여기서 필요한 것은 두 번째다.
                # 이름을 입히는 쪽은 bringup 안의 `PushROSNamespace` 이고 그것은
                # `IfCondition(use_namespace)` 로 묶여 있다. 그래서
                # `use_namespace` 를 끈 채 namespace 를 주면 이름은 바깥
                # PushRosNamespace 하나만 입히고 두 번 접히지 않는다.
                #
                # 두 번째가 파라미터 root key 다. nav2 는
                # `RewrittenYaml(root_key=namespace)` 로 파라미터 파일 전체를
                # namespace 아래에 감싼다. 빈 문자열이면 그 감싸기가 사라져 키가
                # `controller_server` 로 남는데 노드는 `/pinky_01/controller_server`
                # 라서 파라미터가 한 개도 붙지 않고 조용히 기본값으로 뜬다.
                # controller_server 가 기본 플러그인 DWB 를 집어 들어
                # `No critics defined for FollowPath` 로 죽고 AMCL 이
                # `set_initial_pose` 를 못 받아 위치추정을 시작하지 못한 원인이다.
                "namespace": namespace,
                "use_namespace": "false",
                # 합성(composition)은 반드시 꺼야 한다. nav2_bringup 의
                # `ComposableNode` 에는 namespace 인자가 없어서, 바깥
                # PushRosNamespace 는 컨테이너 프로세스에만 붙고 그 안에 적재된
                # AMCL·map_server 에는 전파되지 않는다. 켜 둔 채로 두 대를
                # 띄우면 두 로봇이 루트의 `/amcl_pose` 와 `/map` 하나를 함께
                # 쓰게 되어 위치추정이 서로를 덮어쓴다. 비합성 분기는 평범한
                # `Node` 라 namespace 를 제대로 물려받는다.
                "use_composition": "False",
                "use_sim_time": use_sim_time,
                "autostart": "true",
                "params_file": str(nav2_params),
                "map": LaunchConfiguration("nav2_map"),
                # nav2_bringup 은 `slam` 을 PythonExpression 안에 그대로 끼워
                # 넣는다. 그래서 `true` 가 아니라 파이썬 리터럴 `True` 여야
                # 하고, 아니면 launch 전체가 NameError 로 죽는다.
                "slam": "True" if _enabled(context, "nav2_slam") else "False",
                }.items(),
                condition=IfCondition(LaunchConfiguration("start_nav2")),
            ),
        ]),
        Node(
            package="trihouse_pinky_fleet",
            executable="status_node",
            name="trihouse_status",
            output="screen",
            parameters=[{
                "robot_id": robot_id,
                "map_revision": map_revision,
                "use_sim_time": use_sim_time,
                # map 은 두 로봇이 공유하므로 접두사가 없다. base 프레임에는 위의
                # `frame_prefix` 가 접두사를 붙여 두었으므로 그 이름을 그대로 준다.
                "map_frame": "map",
                "base_frame_id": f"{namespace}/base_footprint",
            }],
            # status_node 는 map pose 를 `map -> base` 변환에서 읽고, 그 변환은
            # AMCL 이 낸다. nav2 가 자기 노드 전부에 같은 remap 을 걸어 두어서
            # AMCL 은 `/<namespace>/tf` 로 방송하므로 여기도 같은 곳을 봐야 한다.
            remappings=[("/tf", "tf"), ("/tf_static", "tf_static")],
        ),
        # 아래 네 노드가 없으면 `dispatchable` 이 영영 false 로 남고 RMF 는 이
        # 로봇에 작업을 주지 않는다 — 주행과 위치추정이 완벽해도 그렇다. adapter 가
        # status 의 그 값을 자기 `ready` 로 복사하기 때문이다. 오류가 아니라 발행자가
        # 없는 것이라 조용하고, 그래서 찾기 어려웠다.
        #
        # 여기 있는 것은 그 판정에 실제로 들어가는 것만이다. `safety_supervisor` 와
        # `recovery_health` 와 `fleet_node` 는 빠져 있다 — safety 는 기본값이 이미
        # clear 이고 나머지 둘은 이 판정에 들어가지 않는다. 이름은 모두 상대
        # 이름이라 위의 PushRosNamespace 가 로봇 아래로 넣어 준다.
        #
        # `trihouse/battery` 를 낸다. 실기에서는 trihouse_pinky_io 의
        # battery_adapter 가 같은 자리를 맡는다.
        Node(
            package="trihouse_pinky_bringup",
            executable="sim_hardware",
            name="trihouse_sim_hardware",
            output="screen",
            parameters=[{"use_sim_time": use_sim_time}],
        ),
        # `trihouse/battery/condition` 을 낸다. 아래 battery_policy 의 입력이다.
        Node(
            package="trihouse_pinky_fleet",
            executable="battery_condition",
            name="trihouse_battery_condition",
            output="screen",
            parameters=[{"robot_id": robot_id, "use_sim_time": use_sim_time}],
        ),
        # `trihouse/battery/policy_state` 를 낸다. `battery_not_dispatchable` 이
        # 이것 없이는 풀리지 않는다.
        Node(
            package="trihouse_pinky_fleet",
            executable="battery_policy",
            name="trihouse_battery_policy",
            output="screen",
            parameters=[{"use_sim_time": use_sim_time}],
        ),
        # `trihouse/readiness` 를 낸다. scan·odom 신선도와 `navigate_to_pose`
        # 액션 서버 가용을 함께 보므로, nav2 navigation 이 활성이어야 READY 가 된다.
        Node(
            package="trihouse_pinky_bringup",
            executable="readiness_checker",
            name="trihouse_readiness",
            output="screen",
            parameters=[{"robot_id": robot_id, "use_sim_time": use_sim_time}],
        ),
        # Nav2 의 속도 명령을 모터까지 잇는 유일한 노드다. launch 가 Nav2 를
        # `cmd_vel -> cmd_vel_nav` 로 remap 하고, gz bridge 는 `cmd_vel` 을 Gazebo 로
        # 넘긴다. 그 사이를 이 노드가 안전 gate 로 통과시킨다. 없으면 경로는
        # 계획되고 step 은 running 이 되는데 **로봇이 영원히 움직이지 않는다.**
        Node(
            package="trihouse_pinky_safety",
            executable="safety_supervisor",
            name="trihouse_safety_supervisor",
            output="screen",
            parameters=[{
                "robot_id": robot_id,
                "use_sim_time": use_sim_time,
                # 시뮬에는 초음파가 없다. `sim_hardware` 가 내는 것은
                # `trihouse/proximity/front` 하나이고 그것으로 충분하다. 켜 두면
                # 센서 미달로 gate 가 계속 정지를 걸어 로봇이 못 움직인다.
                "require_ultrasonic": False,
                # 신선도 판정만 시뮬 주기에 맞춘다. 안전 임계(정지·감속 거리)는
                # 실기와 같게 둔다. 기본 0.5초는 시뮬 센서 주기와 RTF<1 을 견디지
                # 못해 gate 가 깜빡이고, 그 깜빡임이 로봇을 RMF 에서 빼낸다.
                "sensor_timeout_s": 2.0,
            }],
        ),
        # RMF fleet adapter 가 낙찰된 작업을 넘기는 `trihouse/transport/execute`
        # action 의 **서버**다. `fleet_gateway` 는 같은 action 의 클라이언트이므로
        # 이것이 없으면 adapter 는 "ExecuteTransport action server 가 없습니다" 만
        # 반복하고 로봇은 움직이지 않는다. 실기 launch 에는 처음부터 있었다.
        Node(
            package="trihouse_pinky_fleet",
            executable="fleet_node",
            name="trihouse_fleet",
            output="screen",
            parameters=[{
                "robot_id": robot_id,
                "map_revision": map_revision,
                "use_sim_time": use_sim_time,
                # 협로 존 표. 통로 폭 0.20 m 에 로봇 필요 폭 0.14 m 라 Nav2 로는
                # 지날 수 없어(AMCL 오차 0.08~0.11 m) 규칙 주행으로 넘긴다.
                # 값이 지도 좌표계에 묶여 있어 이름이 맞지 않으면 노드가 거절한다.
                "narrow_zones_file": narrow_zones_file,
                "narrow_map_name": narrow_map_name,
            }],
        ),
        # `trihouse/fms/state` 를 낸다. FMS Gateway 의 TCP 포트에 붙으면 ONLINE 이
        # 되고 `control_link_offline` 이 풀린다. 그 포트는 compose.control.yaml 이
        # `FMS_TCP_PORT` 로 내보낸다.
        Node(
            package="trihouse_pinky_fleet",
            executable="fleet_gateway",
            name="trihouse_fleet_gateway",
            output="screen",
            parameters=[{
                "robot_id": robot_id,
                "use_sim_time": use_sim_time,
                "control_host": LaunchConfiguration("fms_tcp_host"),
                "control_port": ParameterValue(
                    LaunchConfiguration("fms_tcp_port"), value_type=int,
                ),
                # 기본값은 `/tmp/trihouse_event_outbox_<pid>.sqlite3` 라서 프로세스
                # 마다 새로 생긴다. 그러면 session 과 sequence 가 매번 초기화되어
                # 재전송과 ACK 의 근거가 사라지므로 로봇마다 고정 경로를 준다.
                "event_outbox_path": PathJoinSubstitution([
                    LaunchConfiguration("runtime_state_dir"),
                    f"{namespace}_task_events.sqlite3",
                ]),
            }],
        ),
    ]
    return GroupAction(actions=actions)


def _runtime(context):
    features_path = Path(
        LaunchConfiguration("physical_features_file").perform(context)
    ).expanduser().resolve()
    if not features_path.is_file():
        raise RuntimeError(f"승인된 physical-feature JSONL이 없습니다: {features_path}")
    nav_graph = Path(
        LaunchConfiguration("nav_graph").perform(context)
    ).expanduser().resolve()
    if not nav_graph.is_file():
        raise RuntimeError(
            f"등록된 로봇·충전기·Waypoint로 생성한 bootstrap graph가 없습니다: {nav_graph}"
        )
    world = Path(LaunchConfiguration("world").perform(context)).expanduser().resolve()
    poses = charger_spawn_poses(features_path)
    # adapter 는 nav_graph 가 쓰는 이름을 받아야 한다. location_code 를 주면 로봇이
    # fleet 에 등록되지 못하고 낙찰이 나지 않는다.
    charger_names = charger_graph_names(features_path)
    robots = selected_robots(context)

    actions = []

    # RMF core는 정확히 하나만 뜬다. 두 fleet adapter가 같은 schedule에 붙는다.
    if _enabled(context, "start_rmf_core"):
        actions.append(
            IncludeLaunchDescription(
                AnyLaunchDescriptionSource(
                    str(Path(__file__).with_name("rmf_core.launch.py"))
                ),
                launch_arguments={
                    "use_sim_time": LaunchConfiguration("use_sim_time"),
                }.items(),
            )
        )

    if _enabled(context, "start_gazebo"):
        if not world.is_file():
            raise RuntimeError(f"Gazebo world가 없습니다: {world}")
        # Gazebo 는 mesh 와 커스텀 plugin 을 이 경로들에서만 찾는다. 없으면
        # 모델이 형상 없이 생성되거나 lamp plugin 을 못 찾는다. `pinky_gz_sim`
        # 의 launch 가 쓰는 것과 같은 구성이다.
        description_share = Path(get_package_share_directory("pinky_description"))
        gz_sim_share = Path(get_package_share_directory("pinky_gz_sim"))
        gz_sim_prefix = gz_sim_share.parents[1]
        actions.append(
            SetEnvironmentVariable(
                "GZ_SIM_RESOURCE_PATH",
                os.pathsep.join([
                    str(description_share.parent),
                    str(gz_sim_share / "models"),
                    os.environ.get("GZ_SIM_RESOURCE_PATH", ""),
                ]).rstrip(os.pathsep),
            )
        )
        actions.append(
            SetEnvironmentVariable(
                "GZ_SIM_SYSTEM_PLUGIN_PATH",
                os.pathsep.join([
                    str(gz_sim_prefix / "lib"),
                    os.environ.get("GZ_SIM_SYSTEM_PLUGIN_PATH", ""),
                ]).rstrip(os.pathsep),
            )
        )
        gz_args = f"-r -s -v2 {world}"
        if _enabled(context, "headless"):
            gz_args = f"-r -s -v2 --headless-rendering {world}"
        actions.append(
            ExecuteProcess(cmd=["gz", "sim", *gz_args.split()], output="screen")
        )
        # 시뮬레이션 시계와 TF 는 두 로봇이 함께 쓰므로 한 번만 넘긴다.
        actions.append(
            Node(
                package="ros_gz_bridge",
                executable="parameter_bridge",
                name="trihouse_world_bridge",
                output="screen",
                arguments=list(WORLD_BRIDGE_TOPICS),
                parameters=[{"use_sim_time": LaunchConfiguration("use_sim_time")}],
            )
        )

    groups = [
        _robot_group(
            context,
            robot_id=robot_id,
            namespace=namespace,
            charger_code=charger_names[robot_id],
            spawn_pose=poses[robot_id],
            nav_graph=nav_graph,
        )
        for robot_id, namespace, charger_code in robots
    ]

    # 로봇별 bridge 는 namespace 밖에서 띄운다. `parameter_bridge` 는 준 이름을
    # gz 와 ROS 양쪽에 그대로 쓰므로, namespace 안에서 띄우면 ROS 쪽이
    # `/pinky_01/pinky_01/scan` 이 되어 버린다.
    bridges = [
        Node(
            package="ros_gz_bridge",
            executable="parameter_bridge",
            name=f"trihouse_bridge_{namespace}",
            output="screen",
            arguments=[f"{namespace}/{topic}" for topic in ROBOT_BRIDGE_TOPICS],
            parameters=[{"use_sim_time": LaunchConfiguration("use_sim_time")}],
        )
        for _robot_id, namespace, _charger in robots
    ]

    # `odom -> base_footprint` 는 robot_state_publisher 가 아니라 Gazebo 의
    # DiffDrive 플러그인이 낸다. 그것 없이는 정적 사슬만 있어서 AMCL 이 스캔을
    # 여전히 맞출 수 없다. URDF 가 gz `/tf` 로 내보내므로(`<tf_topic>/tf</tf_topic>`,
    # pinky_pro 는 고치지 않는다) 그 하나를 로봇 namespace 안으로 넣어 준다.
    #
    # gz `/tf` 에는 두 로봇의 odom 변환이 함께 실려서 각 namespace 가 양쪽을 받는다.
    # 프레임 이름에 namespace 가 붙어 있으므로 트리는 그대로 일관되고, 로봇은 자기
    # 변환만 조회한다.
    tf_bridges = [
        Node(
            package="ros_gz_bridge",
            executable="parameter_bridge",
            name=f"trihouse_tf_bridge_{namespace}",
            output="screen",
            arguments=["/tf@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V"],
            parameters=[{"use_sim_time": LaunchConfiguration("use_sim_time")}],
            # bridge 는 준 이름을 gz 와 ROS 양쪽에 쓴다. 그래서 namespace 밖에서
            # 띄우고 ROS 쪽만 옮긴다 — gz 는 계속 `/tf` 를 구독한다.
            remappings=[("/tf", f"/{namespace}/tf")],
        )
        for _robot_id, namespace, _charger in robots
    ]

    actions.append(
        TimerAction(
            period=LaunchConfiguration("startup_delay_s"),
            actions=[
                *groups,
                *bridges,
                *tf_bridges,
                # 러너가 `queued` Job 에 자원을 배정하고 현재 Step 을 outbox 로
                # 내보낸다. 아래 worker 는 그 행을 claim 해 RMF 로 넘긴다.
                # 러너 없이 worker 만 띄우면 claim 할 것이 없어 주문이 로봇을
                # 움직이지 못한다.
                ExecuteProcess(
                    cmd=[
                        "python3", "-m",
                        "control_tower.task_manager.job_runner_node",
                        "--fms-base-url", LaunchConfiguration("fms_base_url"),
                    ],
                    additional_env={
                        "PYTHONPATH": [
                            LaunchConfiguration("trihouse_root"),
                            os.pathsep,
                            EnvironmentVariable("PYTHONPATH", default_value=""),
                        ]
                    },
                    output="screen",
                    condition=IfCondition(LaunchConfiguration("start_job_runner")),
                ),
                # 실행기 워커. omx/pinky 채널을 claim 해 실행하고 Step 을 닫는다.
                ExecuteProcess(
                    cmd=[
                        "python3", "-m",
                        "control_tower.task_manager.executor_worker_node",
                        "--fms-base-url", LaunchConfiguration("fms_base_url"),
                    ],
                    additional_env={
                        "PYTHONPATH": [
                            LaunchConfiguration("trihouse_root"),
                            os.pathsep,
                            EnvironmentVariable("PYTHONPATH", default_value=""),
                        ]
                    },
                    output="screen",
                    condition=IfCondition(LaunchConfiguration("start_executor_worker")),
                ),
                ExecuteProcess(
                    cmd=[
                        "python3", "-m",
                        "control_tower.rmf_adapter.rmf_gateway_worker_node",
                        "--fms-base-url", LaunchConfiguration("fms_base_url"),
                        "--fleet-name", LaunchConfiguration("fleet_name"),
                        "--worker-id", LaunchConfiguration("rmf_worker_id"),
                    ],
                    additional_env={
                        "PYTHONPATH": [
                            LaunchConfiguration("trihouse_root"),
                            os.pathsep,
                            EnvironmentVariable("PYTHONPATH", default_value=""),
                        ]
                    },
                    output="screen",
                    condition=IfCondition(LaunchConfiguration("start_rmf_worker")),
                ),
            ],
        )
    )
    return actions


def generate_launch_description() -> LaunchDescription:
    repository_root = Path(__file__).resolve().parents[2]
    default_features = (
        repository_root
        / "control_system_test"
        / "rmf_control_ui"
        / "data"
        / "import"
        / "trihouse_test_01_physical_features.jsonl"
    )
    return LaunchDescription([
        DeclareLaunchArgument("trihouse_root", default_value=str(repository_root)),
        DeclareLaunchArgument(
            "physical_features_file", default_value=str(default_features)
        ),
        DeclareLaunchArgument("nav_graph"),
        DeclareLaunchArgument("world"),
        DeclareLaunchArgument("nav2_params_file"),
        # 로봇별 파생 Nav2 파라미터가 있는 디렉터리 (`<namespace>.yaml`).
        DeclareLaunchArgument("nav2_params_dir", default_value=""),
        # Nav2 지도. `nav2_slam:=true` 면 지도 없이 slam_toolbox 로 돈다.
        DeclareLaunchArgument("nav2_map", default_value=""),
        DeclareLaunchArgument("nav2_slam", default_value="false"),
        DeclareLaunchArgument("fleet_config"),
        DeclareLaunchArgument("map_revision"),
        DeclareLaunchArgument("project_name", default_value="trihouse_test_01"),
        DeclareLaunchArgument("rmf_map_name", default_value="L1"),
        DeclareLaunchArgument("fleet_name", default_value="trihouse_pinky"),
        DeclareLaunchArgument("rmf_worker_id", default_value="trihouse-rmf-worker"),
        DeclareLaunchArgument("fms_base_url", default_value="http://127.0.0.1:8080"),
        # 띄울 로봇을 고른다. 비어 있으면 전부. 예: `robots:=PK_01`.
        # 개발 PC 한 대에 두 대의 전체 스택은 무겁다. 주문 경로를 증명할 때는 한 대로
        # 줄여 부하라는 변수를 없애는 편이 빠르다.
        DeclareLaunchArgument("robots", default_value=""),
        # `fleet_gateway` 가 붙는 FMS Gateway 의 TCP 경계다. HTTP(8080)와 다른
        # 포트이며 기본값은 `compose.control.yaml` 의 `FMS_TCP_PORT` 와 같다.
        DeclareLaunchArgument("fms_tcp_host", default_value="127.0.0.1"),
        DeclareLaunchArgument("fms_tcp_port", default_value="8788"),
        # 재시작을 넘겨 보존해야 하는 로봇별 상태(event outbox)를 두는 곳.
        DeclareLaunchArgument("runtime_state_dir", default_value=str(repository_root)),
        DeclareLaunchArgument("use_sim_time", default_value="true"),
        DeclareLaunchArgument("headless", default_value="true"),
        DeclareLaunchArgument("start_rmf_core", default_value="true"),
        DeclareLaunchArgument("start_gazebo", default_value="true"),
        DeclareLaunchArgument("start_nav2", default_value="true"),
        DeclareLaunchArgument("start_rmf_worker", default_value="true"),
        DeclareLaunchArgument("start_job_runner", default_value="true"),
        DeclareLaunchArgument("start_executor_worker", default_value="true"),
        # Gazebo 가 world 를 다 읽기 전에 spawn 을 걸면 `create` 가 "Timed out
        # when getting world names" 로 죽는다. 이 호스트에서 8초면 충분했고
        # 여유를 둬서 12초로 잡는다.
        DeclareLaunchArgument("startup_delay_s", default_value="12.0"),
        OpaqueFunction(function=_runtime),
    ])
