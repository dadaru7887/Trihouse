"""FMS 없이 waypoint를 측정할 때 쓰는 root 토픽 기반 안전 수동 주행 launch."""

from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description() -> LaunchDescription:
    """Vendor hardware와 safety를 root topic으로 묶는다.

    teleop은 `cmd_vel_manual`로만 들어오고, 이 launch에서 `cmd_vel`을 발행하는
    노드는 safety_supervisor 하나다. 라이다와 초음파가 끊기면 safety가 정지한다.
    """
    vendor_bringup = PathJoinSubstitution([
        FindPackageShare('pinky_bringup'), 'launch', 'bringup_robot.launch.xml'
    ])

    return LaunchDescription([
        IncludeLaunchDescription(AnyLaunchDescriptionSource(vendor_bringup)),
        Node(package='pinky_sensor_adc', executable='main_node'),
        Node(package='trihouse_pinky_io', executable='ultrasonic_adapter'),
        Node(
            package='trihouse_pinky_safety',
            executable='safety_supervisor',
            parameters=[{
                'manual_mode_enabled': True,
                'manual_command_timeout_s': 0.25,
            }],
        ),
    ])
