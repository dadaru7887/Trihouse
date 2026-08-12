"""Pinky Gazebo, Open-RMF core, EasyFullControl adapter 검증 조합."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    use_sim_time = LaunchConfiguration("use_sim_time")
    start_rmf_core = IfCondition(LaunchConfiguration("start_rmf_core"))

    pinky_sim = PathJoinSubstitution(
        [
            FindPackageShare("trihouse_pinky_bringup"),
            "launch",
            "trihouse_pinky_sim.launch.py",
        ]
    )
    adapter = PathJoinSubstitution(
        [
            FindPackageShare("trihouse_rmf_bridge"),
            "launch",
            "pinky_easy_fleet_adapter.launch.py",
        ]
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("robot_name", default_value="PK-01"),
            DeclareLaunchArgument("rmf_map_name", default_value="L1"),
            DeclareLaunchArgument("charger_waypoint", default_value="충전1"),
            DeclareLaunchArgument(
                "map_revision", default_value="gwanghee-2026-08-12"
            ),
            DeclareLaunchArgument("nav_graph"),
            DeclareLaunchArgument("map"),
            DeclareLaunchArgument("use_sim_time", default_value="true"),
            DeclareLaunchArgument("start_rmf_core", default_value="true"),
            DeclareLaunchArgument("control_host", default_value="127.0.0.1"),
            DeclareLaunchArgument("control_port", default_value="8788"),
            DeclareLaunchArgument("battery_percentage", default_value="1.0"),
            DeclareLaunchArgument("charging", default_value="false"),
            DeclareLaunchArgument(
                "charge_percent_per_second", default_value="1.0"
            ),
            DeclareLaunchArgument(
                "discharge_percent_per_second", default_value="0.0"
            ),
            Node(
                package="rmf_traffic_ros2",
                executable="rmf_traffic_schedule",
                name="rmf_traffic_schedule",
                condition=start_rmf_core,
                parameters=[{"use_sim_time": use_sim_time}],
                output="screen",
            ),
            Node(
                package="rmf_task_ros2",
                executable="rmf_task_dispatcher",
                name="rmf_task_dispatcher",
                condition=start_rmf_core,
                parameters=[{"use_sim_time": use_sim_time}],
                output="screen",
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(pinky_sim),
                launch_arguments={
                    "robot_id": LaunchConfiguration("robot_name"),
                    "map_revision": LaunchConfiguration("map_revision"),
                    "map": LaunchConfiguration("map"),
                    "control_host": LaunchConfiguration("control_host"),
                    "control_port": LaunchConfiguration("control_port"),
                    "use_sim_time": use_sim_time,
                    "battery_percentage": LaunchConfiguration(
                        "battery_percentage"
                    ),
                    "charging": LaunchConfiguration("charging"),
                    "charge_percent_per_second": LaunchConfiguration(
                        "charge_percent_per_second"
                    ),
                    "discharge_percent_per_second": LaunchConfiguration(
                        "discharge_percent_per_second"
                    ),
                }.items(),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(adapter),
                launch_arguments={
                    "nav_graph": LaunchConfiguration("nav_graph"),
                    "robot_name": LaunchConfiguration("robot_name"),
                    "rmf_map_name": LaunchConfiguration("rmf_map_name"),
                    "charger_waypoint": LaunchConfiguration(
                        "charger_waypoint"
                    ),
                    "map_revision": LaunchConfiguration("map_revision"),
                    "use_sim_time": use_sim_time,
                }.items(),
            ),
        ]
    )
