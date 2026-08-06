from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    default_config = PathJoinSubstitution([
        FindPackageShare('trihouse_pinky_vision'),
        'config',
        'pinky_1.yaml',
    ])
    config_file = LaunchConfiguration('config_file')
    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=default_config),
        Node(
            package='trihouse_pinky_vision',
            executable='camera_streamer',
            name='camera_streamer',
            output='screen',
            parameters=[config_file],
        ),
    ])
