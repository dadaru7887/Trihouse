"""Gazebo Pinky용 조합 launch; 실제 센서가 없는 입력은 명시적 mock으로 대체한다."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node, PushRosNamespace, SetRemap
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """실기 launch와 같은 관제·지도·안전 인자를 Gazebo adapter에도 제공한다."""
    robot_id = LaunchConfiguration('robot_id')
    namespace = LaunchConfiguration('namespace')
    map_revision = LaunchConfiguration('map_revision')
    map_path = LaunchConfiguration('map')
    control_host = LaunchConfiguration('control_host')
    control_port = LaunchConfiguration('control_port')
    omx_station_id = LaunchConfiguration('omx_station_id')
    sim = PathJoinSubstitution([FindPackageShare('pinky_gz_sim'), 'launch', 'launch_sim.launch.xml'])
    navigation = PathJoinSubstitution([FindPackageShare('pinky_navigation'), 'launch', 'gz_bringup_launch.xml'])
    return LaunchDescription([
        DeclareLaunchArgument('robot_id', default_value='PK_01'),
        DeclareLaunchArgument('namespace', default_value='pinky_01'),
        DeclareLaunchArgument('map_revision', default_value=''),
        DeclareLaunchArgument('map', default_value=''),
        DeclareLaunchArgument('control_host', default_value='127.0.0.1'),
        DeclareLaunchArgument('control_port', default_value='8788'),
        DeclareLaunchArgument('use_sim_time', default_value='true'),
        DeclareLaunchArgument('vision_enabled', default_value='false'),
        DeclareLaunchArgument('docking_enabled', default_value='false'),
        DeclareLaunchArgument('omx_station_id', default_value='station-1'),
        DeclareLaunchArgument('battery_percentage', default_value='1.0'),
        DeclareLaunchArgument('charging', default_value='false'),
        DeclareLaunchArgument(
            'charge_percent_per_second', default_value='1.0'
        ),
        DeclareLaunchArgument(
            'discharge_percent_per_second', default_value='0.0'
        ),
        IncludeLaunchDescription(AnyLaunchDescriptionSource(sim)),
        # use_composition은 반드시 False다. composed Nav2는 push-ros-namespace를
        # 물려받지 않아 두 로봇이 루트 /amcl_pose와 /map을 공유하게 된다.
        IncludeLaunchDescription(
            AnyLaunchDescriptionSource(navigation),
            launch_arguments={
                'map': map_path,
                'namespace': namespace,
                'use_composition': 'False',
            }.items(),
        ),
        # 이 그룹 안의 모든 것이 /<namespace>/... 아래로 들어간다. Nav2 와 Gazebo
        # include 는 자기 launch 가 namespace 인자를 받아 스스로 적용하므로 여기서
        # 또 감싸지 않는다. 두 번 감싸면 /pinky_01/pinky_01/... 이 된다.
        GroupAction([
            PushRosNamespace(namespace),
            # Nav2만 cmd_vel_nav로 remap하며 모터용 cmd_vel은 safety가 단독 소유한다.
            SetRemap(src='cmd_vel', dst='cmd_vel_nav'),
            Node(
                package='trihouse_pinky_bringup',
                executable='sim_hardware',
                parameters=[{
                    'use_sim_time': True,
                    'battery_percentage': ParameterValue(
                        LaunchConfiguration('battery_percentage'), value_type=float
                    ),
                    'charging': ParameterValue(
                        LaunchConfiguration('charging'), value_type=bool
                    ),
                    'charge_percent_per_second': ParameterValue(
                        LaunchConfiguration('charge_percent_per_second'),
                        value_type=float,
                    ),
                    'discharge_percent_per_second': ParameterValue(
                        LaunchConfiguration('discharge_percent_per_second'),
                        value_type=float,
                    ),
                }],
            ),
            Node(package='trihouse_pinky_safety', executable='safety_supervisor', parameters=[{'robot_id': robot_id, 'use_sim_time': True}]),
            Node(package='trihouse_pinky_bringup', executable='readiness_checker', parameters=[{'robot_id': robot_id, 'use_sim_time': True}]),
            Node(package='trihouse_pinky_fleet', executable='battery_condition', parameters=[{'robot_id': robot_id, 'use_sim_time': True}]),
            Node(package='trihouse_pinky_fleet', executable='battery_policy', parameters=[{'use_sim_time': True}]),
            Node(package='trihouse_pinky_fleet', executable='status_node', parameters=[{'robot_id': robot_id, 'map_revision': map_revision, 'use_sim_time': True}]),
            Node(package='trihouse_pinky_fleet', executable='recovery_health', parameters=[{'robot_id': robot_id, 'use_sim_time': True}]),
            Node(package='trihouse_pinky_fleet', executable='fleet_node', parameters=[{'robot_id': robot_id, 'map_revision': map_revision, 'use_sim_time': True}]),
            Node(package='trihouse_pinky_fleet', executable='fleet_gateway', parameters=[{'robot_id': robot_id, 'control_host': control_host, 'control_port': control_port, 'use_sim_time': True}]),
        ]),
        Node(package='trihouse_omx_adapter', executable='gazebo_omx_adapter', parameters=[{'omx_id': omx_station_id, 'robot_id': robot_id, 'use_sim_time': True}]),
    ])
