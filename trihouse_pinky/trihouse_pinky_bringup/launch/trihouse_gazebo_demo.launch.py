"""Pinky Gazebo, Nav2, mock sensor, Gazebo OMX adapter를 한 graph로 시작하는 데모 launch."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """관제 UI는 별도 PC process로 유지하고 ROS graph 부분만 이 launch가 소유한다."""
    robot_id = LaunchConfiguration('robot_id')
    shared = {name: LaunchConfiguration(name) for name in ('robot_id', 'map_revision', 'map', 'control_host', 'control_port', 'use_sim_time', 'vision_enabled', 'docking_enabled', 'omx_station_id')}
    pinky_launch = PathJoinSubstitution([FindPackageShare('trihouse_pinky_bringup'), 'launch', 'trihouse_pinky_sim.launch.py'])
    return LaunchDescription([
        DeclareLaunchArgument('robot_id', default_value='PK-01'),
        DeclareLaunchArgument('map_revision', default_value=''),
        DeclareLaunchArgument('map', default_value=''),
        DeclareLaunchArgument('control_host', default_value='127.0.0.1'),
        DeclareLaunchArgument('control_port', default_value='8788'),
        DeclareLaunchArgument('use_sim_time', default_value='true'),
        DeclareLaunchArgument('vision_enabled', default_value='false'),
        DeclareLaunchArgument('docking_enabled', default_value='false'),
        DeclareLaunchArgument('omx_station_id', default_value='OMX-01'),
        # trihouse_pinky_sim.launch.py 내부에서 pinky_gz_sim, sim_hardware, gazebo_omx_adapter와
        # Nav2의 /cmd_vel_nav → Safety Supervisor의 단일 /cmd_vel 경계를 시작한다.
        IncludeLaunchDescription(PythonLaunchDescriptionSource(pinky_launch), launch_arguments=shared.items()),
    ])
