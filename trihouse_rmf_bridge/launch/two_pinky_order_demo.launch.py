"""RMF core 하나와 격리된 두 Pinky namespace로 P0 주문 시연을 띄운다.

`PK_01/pinky_01`과 `PK_02/pinky_02`는 스캔·odom·pose·경로 계산·경로 추종·
지역/전역 경로·costmap·상태 토픽을 모두 namespace 아래에서만 주고받는다.
두 로봇의 spawn pose는 승인된 physical-feature JSONL의 충전 스테이션
기록에서만 읽는다. 좌표를 launch 파일에 새로 적지 않는다.

내부 bootstrap graph는 등록된 로봇·충전기·Waypoint에 대해서만 생성되며
운영자 편집 레이어가 아니다.
"""

import os
from pathlib import Path

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    GroupAction,
    IncludeLaunchDescription,
    OpaqueFunction,
    TimerAction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node, PushRosNamespace


# Control Tower가 고정한 Pinky <-> 충전기 결속. 이 표는 운영 정책이며
# 좌표는 항상 승인된 JSONL에서 읽는다.
ROBOT_CHARGERS = (
    ("PK_01", "pinky_01", "TRIHOUSE-TEST-01-CHG-01"),
    ("PK_02", "pinky_02", "TRIHOUSE-TEST-01-CHG-02"),
)

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


def _enabled(context, name: str) -> bool:
    return LaunchConfiguration(name).perform(context).strip().lower() in {
        "1", "true", "yes", "on",
    }


def charger_spawn_poses(features_path: Path) -> dict[str, tuple[float, float, float]]:
    """승인된 JSONL의 충전 스테이션 pose만 로봇별로 돌려준다."""
    import sys

    repository_root = Path(__file__).resolve().parents[2]
    if str(repository_root) not in sys.path:
        sys.path.insert(0, str(repository_root))
    from fms_gateway.app.physical_features import PhysicalFeatureImporter

    imported = PhysicalFeatureImporter().parse(features_path)
    poses: dict[str, tuple[float, float, float]] = {}
    for robot_id, _namespace, charger_code in ROBOT_CHARGERS:
        waypoint = imported.waypoint(charger_code)
        if waypoint.operational_role != "charging_station":
            raise RuntimeError(
                f"{charger_code}는 charging_station이 아닙니다: "
                f"{waypoint.operational_role}"
            )
        if waypoint.pose.yaw is None:
            raise RuntimeError(f"{charger_code}에 측정된 yaw가 없습니다")
        poses[robot_id] = (waypoint.pose.x, waypoint.pose.y, waypoint.pose.yaw)
    return poses


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
    nav2_params = Path(
        LaunchConfiguration("nav2_params_file").perform(context)
    ).expanduser().resolve()
    x, y, yaw = spawn_pose

    actions = [
        PushRosNamespace(namespace),
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
        Node(
            package="nav2_bringup",
            executable="bringup_launch.py",
            name=f"nav2_{namespace}",
            output="screen",
            parameters=[
                str(nav2_params),
                {"use_sim_time": use_sim_time},
            ],
            # 두 스택이 서로의 경로/costmap을 덮어쓰지 않도록 namespace 안에
            # 상대 이름만 쓴다.
            remappings=[(name, name) for name in NAMESPACED_INTERFACES],
            condition=IfCondition(LaunchConfiguration("start_nav2")),
        ),
        Node(
            package="trihouse_pinky_fleet",
            executable="status_node",
            name="trihouse_status",
            output="screen",
            parameters=[{
                "robot_id": robot_id,
                "map_revision": map_revision,
                "use_sim_time": use_sim_time,
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

    actions = []

    # RMF core는 정확히 하나만 뜬다. 두 fleet adapter가 같은 schedule에 붙는다.
    if _enabled(context, "start_rmf_core"):
        actions.append(
            IncludeLaunchDescription(
                AnyLaunchDescriptionSource(
                    str(Path(__file__).with_name("office_energy_bridge.launch.py"))
                ),
                launch_arguments={
                    "nav_graph_file": str(nav_graph),
                    "use_sim_time": LaunchConfiguration("use_sim_time"),
                }.items(),
            )
        )

    if _enabled(context, "start_gazebo"):
        if not world.is_file():
            raise RuntimeError(f"Gazebo world가 없습니다: {world}")
        gz_args = f"-r -s -v2 {world}"
        if _enabled(context, "headless"):
            gz_args = f"-r -s -v2 --headless-rendering {world}"
        actions.append(
            ExecuteProcess(cmd=["gz", "sim", *gz_args.split()], output="screen")
        )

    groups = [
        _robot_group(
            context,
            robot_id=robot_id,
            namespace=namespace,
            charger_code=charger_code,
            spawn_pose=poses[robot_id],
            nav_graph=nav_graph,
        )
        for robot_id, namespace, charger_code in ROBOT_CHARGERS
    ]
    actions.append(
        TimerAction(
            period=LaunchConfiguration("startup_delay_s"),
            actions=[
                *groups,
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
        DeclareLaunchArgument("fleet_config"),
        DeclareLaunchArgument("map_revision"),
        DeclareLaunchArgument("project_name", default_value="trihouse_test_01"),
        DeclareLaunchArgument("rmf_map_name", default_value="L1"),
        DeclareLaunchArgument("fleet_name", default_value="trihouse_pinky"),
        DeclareLaunchArgument("rmf_worker_id", default_value="trihouse-rmf-worker"),
        DeclareLaunchArgument("fms_base_url", default_value="http://127.0.0.1:8080"),
        DeclareLaunchArgument("use_sim_time", default_value="true"),
        DeclareLaunchArgument("headless", default_value="true"),
        DeclareLaunchArgument("start_rmf_core", default_value="true"),
        DeclareLaunchArgument("start_gazebo", default_value="true"),
        DeclareLaunchArgument("start_nav2", default_value="true"),
        DeclareLaunchArgument("start_rmf_worker", default_value="true"),
        DeclareLaunchArgument("startup_delay_s", default_value="5.0"),
        OpaqueFunction(function=_runtime),
    ])
