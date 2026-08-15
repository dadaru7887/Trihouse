"""3온도 물류센터 월드 + Pinky 플릿 + 관제 링크를 한 번에 띄운다.

    ros2 launch robo_pinky_sim warehouse.launch.py

주요 인자
    gui:=false          헤드리스(서버만) 실행
    agents:=false       관제 링크 없이 Gazebo만 (수동 teleop 확인용)
    control_host/port   관제센터 TCP 링크 주소 (기본 127.0.0.1:8788)
    fleet:=<yaml>       띄울 로봇 목록
    scale:=0.1          관제 1 unit 당 미터
"""

from __future__ import annotations

import os

import xacro
import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node

MAP_WIDTH = 120.0
MAP_HEIGHT = 72.0


def _to_world(x_u: float, y_u: float, scale: float) -> tuple[float, float]:
    """관제 좌표(unit) → Gazebo 월드(m). 창고 중심이 원점, y축 반전."""
    return (x_u - MAP_WIDTH / 2) * scale, (MAP_HEIGHT / 2 - y_u) * scale


def _spawn_robots(context, *_args, **_kwargs):
    sim_share = get_package_share_directory("robo_pinky_sim")
    desc_share = get_package_share_directory("robo_pinky_description")

    fleet_path = LaunchConfiguration("fleet").perform(context)
    scale = float(LaunchConfiguration("scale").perform(context))
    control_host = LaunchConfiguration("control_host").perform(context)
    control_port = int(LaunchConfiguration("control_port").perform(context))
    truthy = ("true", "1", "yes")
    with_agents = LaunchConfiguration("agents").perform(context).lower() in truthy
    with_camera = LaunchConfiguration("camera").perform(context).lower() in truthy

    with open(fleet_path, encoding="utf-8") as fp:
        fleet = yaml.safe_load(fp)["robots"]

    xacro_file = os.path.join(desc_share, "urdf", "pinky.urdf.xacro")
    actions = []

    for spec in fleet:
        gz_name = spec["gz_name"]
        urdf = xacro.process_file(
            xacro_file,
            mappings={
                "robot_name": gz_name,
                "body_color": spec.get("body_color", "0.98 0.42 0.65 1.0"),
                "enable_camera": "true" if with_camera else "false",
            },
        ).toxml()

        wx, wy = _to_world(float(spec["spawn_x"]), float(spec["spawn_y"]), scale)
        wyaw = -float(spec.get("spawn_heading", 0.0))

        actions.append(
            Node(
                package="robot_state_publisher",
                executable="robot_state_publisher",
                name="robot_state_publisher",
                namespace=gz_name,
                output="screen",
                parameters=[{"use_sim_time": True, "robot_description": urdf}],
            )
        )

        actions.append(
            Node(
                package="ros_gz_sim",
                executable="create",
                name=f"spawn_{gz_name}",
                output="screen",
                arguments=[
                    "-name", gz_name,
                    "-topic", f"/{gz_name}/robot_description",
                    "-x", f"{wx:.4f}",
                    "-y", f"{wy:.4f}",
                    "-z", "0.02",
                    "-Y", f"{wyaw:.4f}",
                ],
                parameters=[{"use_sim_time": True}],
            )
        )

        actions.append(
            Node(
                package="ros_gz_bridge",
                executable="parameter_bridge",
                name=f"bridge_{gz_name}",
                output="screen",
                parameters=[{"use_sim_time": True}],
                arguments=[
                    f"/{gz_name}/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist",
                    f"/{gz_name}/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry",
                    f"/{gz_name}/scan@sensor_msgs/msg/LaserScan[gz.msgs.LaserScan",
                    f"/{gz_name}/imu@sensor_msgs/msg/Imu[gz.msgs.IMU",
                    f"/{gz_name}/joint_states@sensor_msgs/msg/JointState[gz.msgs.Model",
                    f"/{gz_name}/tf@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V",
                    *(
                        [
                            f"/{gz_name}/camera/image_raw@sensor_msgs/msg/Image[gz.msgs.Image",
                            f"/{gz_name}/camera/camera_info@sensor_msgs/msg/CameraInfo"
                            "[gz.msgs.CameraInfo",
                        ]
                        if with_camera
                        else []
                    ),
                ],
                remappings=[(f"/{gz_name}/tf", "/tf")],
            )
        )

        if with_agents:
            actions.append(
                Node(
                    package="robo_pinky_agent",
                    executable="pinky_agent",
                    name=f"agent_{gz_name}",
                    output="screen",
                    parameters=[
                        {
                            "use_sim_time": True,
                            "robot_id": spec["id"],
                            "robot_name": spec["name"],
                            "robot_model": spec["model"],
                            "zones": list(spec["zones"]),
                            "home_charger": spec["home_charger"],
                            "gz_name": gz_name,
                            "spawn_x": float(spec["spawn_x"]),
                            "spawn_y": float(spec["spawn_y"]),
                            "spawn_heading": float(spec.get("spawn_heading", 0.0)),
                            "control_host": control_host,
                            "control_port": control_port,
                            "scale": scale,
                            "map_width": MAP_WIDTH,
                            "map_height": MAP_HEIGHT,
                        }
                    ],
                )
            )

    actions += _spawn_arms(
        sim_share, desc_share, scale, control_host, control_port, with_agents,
        LaunchConfiguration("arms").perform(context),
    )
    return actions


def _spawn_arms(
    sim_share, desc_share, scale, control_host, control_port, with_agents, fleet_path
):
    """구획 적재 스테이션의 OMX 로봇팔을 띄운다."""
    if not fleet_path or fleet_path.lower() in ("none", "false", ""):
        return []
    with open(fleet_path, encoding="utf-8") as fp:
        arms = yaml.safe_load(fp).get("arms", [])

    xacro_file = os.path.join(desc_share, "urdf", "omx.urdf.xacro")
    actions = []

    for spec in arms:
        gz_name = spec["gz_name"]
        urdf = xacro.process_file(
            xacro_file,
            mappings={
                "arm_name": gz_name,
                "body_color": spec.get("body_color", "0.90 0.90 0.92 1.0"),
            },
        ).toxml()

        wx, wy = _to_world(float(spec["mount_x"]), float(spec["mount_y"]), scale)
        wyaw = -float(spec.get("mount_heading", 0.0))

        actions.append(
            Node(
                package="robot_state_publisher",
                executable="robot_state_publisher",
                name="robot_state_publisher",
                namespace=gz_name,
                output="screen",
                parameters=[{"use_sim_time": True, "robot_description": urdf}],
            )
        )
        actions.append(
            Node(
                package="ros_gz_sim",
                executable="create",
                name=f"spawn_{gz_name}",
                output="screen",
                arguments=[
                    "-name", gz_name,
                    "-topic", f"/{gz_name}/robot_description",
                    "-x", f"{wx:.4f}",
                    "-y", f"{wy:.4f}",
                    "-z", "0.0",
                    "-Y", f"{wyaw:.4f}",
                ],
                parameters=[{"use_sim_time": True}],
            )
        )
        actions.append(
            Node(
                package="ros_gz_bridge",
                executable="parameter_bridge",
                name=f"bridge_{gz_name}",
                output="screen",
                parameters=[{"use_sim_time": True}],
                arguments=[
                    *(
                        f"/{gz_name}/{j}_cmd@std_msgs/msg/Float64]gz.msgs.Double"
                        for j in (
                            "joint1",
                            "joint2",
                            "joint3",
                            "joint4",
                            "gripper_left_joint",
                            "gripper_right_joint",
                        )
                    ),
                    f"/{gz_name}/joint_states@sensor_msgs/msg/JointState[gz.msgs.Model",
                ],
            )
        )
        if with_agents:
            actions.append(
                Node(
                    package="robo_pinky_agent",
                    executable="pinky_arm_agent",
                    name=f"arm_{gz_name}",
                    output="screen",
                    parameters=[
                        {
                            "use_sim_time": True,
                            "arm_id": spec["id"],
                            "arm_model": spec.get("model", "OMX-LOADER"),
                            "gz_name": gz_name,
                            "station": spec["station"],
                            "zone": spec["zone"],
                            "mount_x": float(spec["mount_x"]),
                            "mount_y": float(spec["mount_y"]),
                            "mount_heading": float(spec.get("mount_heading", 0.0)),
                            "control_host": control_host,
                            "control_port": control_port,
                            "scale": scale,
                            "map_width": MAP_WIDTH,
                            "map_height": MAP_HEIGHT,
                        }
                    ],
                )
            )

    del sim_share
    return actions


def generate_launch_description() -> LaunchDescription:
    sim_share = get_package_share_directory("robo_pinky_sim")

    args = [
        DeclareLaunchArgument(
            "world",
            default_value=os.path.join(sim_share, "worlds", "warehouse_3temp.sdf"),
            description="불러올 월드 SDF",
        ),
        DeclareLaunchArgument(
            "fleet",
            default_value=os.path.join(sim_share, "config", "fleet.yaml"),
            description="스폰할 Pinky 목록",
        ),
        DeclareLaunchArgument(
            "arms",
            default_value=os.path.join(sim_share, "config", "arms.yaml"),
            description="구획 적재 스테이션 로봇팔 목록. none이면 띄우지 않는다",
        ),
        DeclareLaunchArgument("gui", default_value="true", description="Gazebo GUI 표시"),
        DeclareLaunchArgument(
            "agents", default_value="true", description="관제 링크 에이전트 실행"
        ),
        DeclareLaunchArgument(
            "camera",
            default_value="false",
            description="전방 카메라 센서 사용(로봇 대수만큼 GPU 렌더 부하가 늘어난다)",
        ),
        DeclareLaunchArgument("control_host", default_value="127.0.0.1"),
        DeclareLaunchArgument("control_port", default_value="8788"),
        DeclareLaunchArgument(
            "scale", default_value="0.1", description="관제 1 unit 당 미터"
        ),
    ]

    gz_launch = os.path.join(
        get_package_share_directory("ros_gz_sim"), "launch", "gz_sim.launch.py"
    )

    server = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(gz_launch),
        launch_arguments={
            "gz_args": PythonExpression(
                ["'-r -s -v3 ' + '", LaunchConfiguration("world"), "'"]
            ),
            "on_exit_shutdown": "true",
        }.items(),
    )

    # GUI는 필수 프로세스가 아니다. 창을 닫거나 렌더러가 죽어도 물리 시뮬레이션과
    # 관제 링크는 계속 돌아야 한다(`gz sim -g`로 다시 붙일 수 있다).
    gui = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(gz_launch),
        launch_arguments={
            "gz_args": "-g -v3",
            "on_exit_shutdown": "false",
        }.items(),
        condition=IfCondition(LaunchConfiguration("gui")),
    )

    clock_bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        name="clock_bridge",
        output="screen",
        arguments=["/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock"],
    )

    return LaunchDescription(
        args + [server, gui, clock_bridge, OpaqueFunction(function=_spawn_robots)]
    )
