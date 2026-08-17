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
    Command,
    EnvironmentVariable,
    LaunchConfiguration,
    PathJoinSubstitution,
)
from launch_ros.actions import Node, PushRosNamespace
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


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
                    Command([
                        "xacro ",
                        PathJoinSubstitution([
                            FindPackageShare("pinky_description"),
                            "urdf",
                            "robot.urdf.xacro",
                        ]),
                        f" namespace:={namespace}/",
                        " is_sim:=True",
                    ]),
                    value_type=str,
                ),
            }],
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
        IncludeLaunchDescription(
            AnyLaunchDescriptionSource(
                str(
                    Path(get_package_share_directory("nav2_bringup"))
                    / "launch"
                    / "bringup_launch.py"
                )
            ),
            launch_arguments={
                # 이미 PushRosNamespace 안이다. 여기서 namespace 를 또 주면
                # nav2 노드가 `/pinky_01/pinky_01/...` 로 두 번 접힌다.
                "namespace": "",
                "use_namespace": "false",
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
            charger_code=charger_code,
            spawn_pose=poses[robot_id],
            nav_graph=nav_graph,
        )
        for robot_id, namespace, charger_code in ROBOT_CHARGERS
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
        for _robot_id, namespace, _charger in ROBOT_CHARGERS
    ]

    actions.append(
        TimerAction(
            period=LaunchConfiguration("startup_delay_s"),
            actions=[
                *groups,
                *bridges,
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
        DeclareLaunchArgument("use_sim_time", default_value="true"),
        DeclareLaunchArgument("headless", default_value="true"),
        DeclareLaunchArgument("start_rmf_core", default_value="true"),
        DeclareLaunchArgument("start_gazebo", default_value="true"),
        DeclareLaunchArgument("start_nav2", default_value="true"),
        DeclareLaunchArgument("start_rmf_worker", default_value="true"),
        DeclareLaunchArgument("start_job_runner", default_value="true"),
        # Gazebo 가 world 를 다 읽기 전에 spawn 을 걸면 `create` 가 "Timed out
        # when getting world names" 로 죽는다. 이 호스트에서 8초면 충분했고
        # 여유를 둬서 12초로 잡는다.
        DeclareLaunchArgument("startup_delay_s", default_value="12.0"),
        OpaqueFunction(function=_runtime),
    ])
