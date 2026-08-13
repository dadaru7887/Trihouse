"""실물 Pinky EasyFullControl adapter 실행."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    default_config = PathJoinSubstitution(
        [FindPackageShare("trihouse_rmf_bridge"), "config", "pinky_fleet.yaml"]
    )

    common_arguments = [
        "--config-file",
        LaunchConfiguration("config_file"),
        "--nav-graph",
        LaunchConfiguration("nav_graph"),
        "--robot-name",
        LaunchConfiguration("robot_name"),
        "--rmf-map-name",
        LaunchConfiguration("rmf_map_name"),
        "--charger-waypoint",
        LaunchConfiguration("charger_waypoint"),
        "--map-revision",
        LaunchConfiguration("map_revision"),
        "--status-topic",
        LaunchConfiguration("robot_status_topic"),
        "--transport-action",
        LaunchConfiguration("transport_action"),
        "--fms-base-url",
        LaunchConfiguration("fms_base_url"),
        "--fms-timeout",
        LaunchConfiguration("fms_timeout"),
    ]

    return LaunchDescription(
        [
            DeclareLaunchArgument("config_file", default_value=default_config),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument(
                "nav_graph",
                description="실물 map revision과 일치하는 RMF navigation graph YAML",
            ),
            DeclareLaunchArgument("robot_name", default_value="PK_01"),
            DeclareLaunchArgument("rmf_map_name", default_value="L1"),
            DeclareLaunchArgument("charger_waypoint", default_value="충전1"),
            DeclareLaunchArgument("map_revision"),
            DeclareLaunchArgument("robot_status_topic", default_value="/trihouse/status"),
            DeclareLaunchArgument(
                "transport_action", default_value="/trihouse/transport/execute"
            ),
            DeclareLaunchArgument("fms_base_url", default_value="http://127.0.0.1:8080"),
            DeclareLaunchArgument("fms_timeout", default_value="2.0"),
            Node(
                package="trihouse_rmf_bridge",
                executable="pinky_easy_fleet_adapter",
                name="pinky_easy_fleet_adapter",
                output="screen",
                condition=IfCondition(LaunchConfiguration("use_sim_time")),
                arguments=[*common_arguments, "--use-sim-time"],
            ),
            Node(
                package="trihouse_rmf_bridge",
                executable="pinky_easy_fleet_adapter",
                name="pinky_easy_fleet_adapter",
                output="screen",
                condition=UnlessCondition(LaunchConfiguration("use_sim_time")),
                arguments=common_arguments,
            ),
        ]
    )
