"""실기 Pinky용 최상위 조합 launch; 벤더 `pinky_pro`는 include만 한다."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node, SetRemap
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """실기와 Gazebo가 공유하는 업무 인자를 각 onboard adapter에 전달한다."""
    robot_id = LaunchConfiguration('robot_id')
    map_revision = LaunchConfiguration('map_revision')
    map_path = LaunchConfiguration('map')
    control_host = LaunchConfiguration('control_host')
    control_port = LaunchConfiguration('control_port')
    font_path = LaunchConfiguration('font_path')
    omx_station_id = LaunchConfiguration('omx_station_id')
    vendor_bringup = PathJoinSubstitution([FindPackageShare('pinky_bringup'), 'launch', 'bringup_robot.launch.xml'])
    navigation = PathJoinSubstitution([FindPackageShare('pinky_navigation'), 'launch', 'bringup_launch.xml'])
    return LaunchDescription([
        DeclareLaunchArgument('robot_id', default_value='PK-01'),
        DeclareLaunchArgument('map_revision', default_value=''),
        DeclareLaunchArgument('map', default_value=''),
        DeclareLaunchArgument('control_host', default_value='127.0.0.1'),
        DeclareLaunchArgument('control_port', default_value='8788'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('vision_enabled', default_value='false'),
        DeclareLaunchArgument('docking_enabled', default_value='false'),
        DeclareLaunchArgument('omx_station_id', default_value='station-1'),
        DeclareLaunchArgument('font_path', default_value=''),
        # Nav2만 /cmd_vel_nav로 remap하며 모터용 /cmd_vel은 safety가 단독 소유한다.
        GroupAction([SetRemap(src='/cmd_vel', dst='/cmd_vel_nav'), IncludeLaunchDescription(AnyLaunchDescriptionSource(navigation), launch_arguments={'map': map_path}.items())]),
        IncludeLaunchDescription(AnyLaunchDescriptionSource(vendor_bringup)),
        Node(package='pinky_imu_bno055', executable='main_node'),
        Node(package='pinky_sensor_adc', executable='main_node'),
        Node(package='trihouse_pinky_io', executable='battery_adapter'),
        Node(package='trihouse_pinky_io', executable='ultrasonic_adapter'),
        Node(package='trihouse_pinky_io', executable='led_indicator_client'),
        Node(package='trihouse_pinky_io', executable='buzzer_indicator_client'),
        Node(package='trihouse_pinky_io', executable='destination_display', parameters=[{'font_path': font_path}]),
        Node(package='trihouse_pinky_safety', executable='safety_supervisor', parameters=[{'robot_id': robot_id}]),
        Node(package='trihouse_pinky_bringup', executable='readiness_checker', parameters=[{'robot_id': robot_id}]),
        Node(package='trihouse_pinky_fleet', executable='status_node', parameters=[{'robot_id': robot_id}]),
        Node(package='trihouse_pinky_fleet', executable='recovery_health', parameters=[{'robot_id': robot_id}]),
        Node(package='trihouse_pinky_fleet', executable='fleet_node', parameters=[{'robot_id': robot_id, 'map_revision': map_revision}]),
        Node(package='trihouse_pinky_fleet', executable='fleet_gateway', parameters=[{'robot_id': robot_id, 'control_host': control_host, 'control_port': control_port}]),
        # 실기 OMX endpoint는 검증 전 motion을 내보내지 않는 skeleton으로만 포함한다.
        Node(package='trihouse_omx_adapter', executable='hardware_omx_adapter', parameters=[{'omx_id': omx_station_id}]),
    ])
