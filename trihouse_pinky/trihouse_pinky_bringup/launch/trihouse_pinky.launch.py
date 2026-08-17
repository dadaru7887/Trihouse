"""실기 Pinky용 최상위 조합 launch; 벤더 `pinky_pro`는 include만 한다."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node, PushRosNamespace, SetRemap
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """실기와 Gazebo가 공유하는 업무 인자를 각 onboard adapter에 전달한다.

    로봇 구분은 ROS namespace 로 한다. `namespace:=pinky_02` 를 주면 이 launch 가
    띄우는 모든 onboard 노드의 토픽이 `/pinky_02/...` 로 간다. 노드 소스가 토픽을
    상대 이름으로 적고 있기 때문에 `PushRosNamespace` 만으로 접두사가 붙는다 —
    앞에 `/` 가 붙은 절대 이름은 namespace 를 통째로 무시하므로 그렇게 적으면
    안 된다(`test_namespace_contract.py` 가 지킨다).

    `robot_id`(`PK_01`)와 `namespace`(`pinky_01`)는 서로 다른 표기이며 섞지
    않는다. 앞의 것은 관제·감사용 식별자로 메시지 본문에 실리고, 뒤의 것은 DDS
    이름 공간이다. 둘의 짝은 `two_pinky_order_demo.launch.py` 의 표가 정본이다.
    """
    robot_id = LaunchConfiguration('robot_id')
    namespace = LaunchConfiguration('namespace')
    map_revision = LaunchConfiguration('map_revision')
    map_path = LaunchConfiguration('map')
    control_host = LaunchConfiguration('control_host')
    control_port = LaunchConfiguration('control_port')
    font_path = LaunchConfiguration('font_path')
    omx_station_id = LaunchConfiguration('omx_station_id')
    vendor_bringup = PathJoinSubstitution([FindPackageShare('pinky_bringup'), 'launch', 'bringup_robot.launch.xml'])
    navigation = PathJoinSubstitution([FindPackageShare('pinky_navigation'), 'launch', 'bringup_launch.xml'])
    return LaunchDescription([
        DeclareLaunchArgument('robot_id', default_value='PK_01'),
        DeclareLaunchArgument('namespace', default_value='pinky_01'),
        DeclareLaunchArgument('map_revision', default_value=''),
        DeclareLaunchArgument('map', default_value=''),
        DeclareLaunchArgument('control_host', default_value='127.0.0.1'),
        DeclareLaunchArgument('control_port', default_value='8788'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('vision_enabled', default_value='false'),
        DeclareLaunchArgument('docking_enabled', default_value='false'),
        DeclareLaunchArgument('omx_station_id', default_value='station-1'),
        DeclareLaunchArgument('font_path', default_value=''),
        # 이 그룹 안의 모든 것이 `/<namespace>/...` 아래로 들어간다. 벤더
        # bringup 과 Nav2 는 자기 launch 가 `namespace` 인자를 받아 스스로
        # `push-ros-namespace` 를 적용하므로, 여기서 또 감싸지 않고 인자로만
        # 넘긴다. 두 번 감싸면 `/pinky_01/pinky_01/...` 이 된다.
        GroupAction([
            PushRosNamespace(namespace),
            # Nav2만 cmd_vel_nav로 remap하며 모터용 cmd_vel은 safety가 단독 소유한다.
            # 상대 이름으로 적어야 namespace 안에서 해석된다.
            SetRemap(src='cmd_vel', dst='cmd_vel_nav'),
            # 벤더 센서 노드도 같은 namespace 안에 둔다. 밖에 두면 batt_state 와
            # us_sensor/range 가 루트에 남아 아래 adapter 들이 아무것도 못 받는다.
            Node(package='pinky_imu_bno055', executable='main_node'),
            Node(package='pinky_sensor_adc', executable='main_node'),
            Node(package='trihouse_pinky_io', executable='battery_adapter'),
            Node(package='trihouse_pinky_io', executable='ultrasonic_adapter'),
            Node(package='trihouse_pinky_io', executable='led_indicator_client'),
            Node(package='trihouse_pinky_io', executable='buzzer_indicator_client'),
            Node(package='trihouse_pinky_io', executable='destination_display', parameters=[{'font_path': font_path}]),
            Node(package='trihouse_pinky_safety', executable='safety_supervisor', parameters=[{'robot_id': robot_id}]),
            Node(package='trihouse_pinky_bringup', executable='readiness_checker', parameters=[{'robot_id': robot_id}]),
            Node(package='trihouse_pinky_fleet', executable='battery_condition', parameters=[{'robot_id': robot_id}]),
            Node(package='trihouse_pinky_fleet', executable='battery_policy'),
            Node(package='trihouse_pinky_fleet', executable='status_node', parameters=[{'robot_id': robot_id, 'map_revision': map_revision}]),
            Node(package='trihouse_pinky_fleet', executable='recovery_health', parameters=[{'robot_id': robot_id}]),
            Node(package='trihouse_pinky_fleet', executable='fleet_node', parameters=[{'robot_id': robot_id, 'map_revision': map_revision}]),
            Node(package='trihouse_pinky_fleet', executable='fleet_gateway', parameters=[{'robot_id': robot_id, 'control_host': control_host, 'control_port': control_port}]),
        ]),
        # `use_composition`은 반드시 False다. composed Nav2는 `push-ros-namespace`를
        # 물려받지 않아서 두 로봇이 루트 `/amcl_pose`와 `/map`을 공유하게 된다.
        IncludeLaunchDescription(
            AnyLaunchDescriptionSource(navigation),
            launch_arguments={
                'map': map_path,
                'namespace': namespace,
                'use_composition': 'False',
            }.items(),
        ),
        # 벤더 bringup은 로봇마다 `namespace` 인자를 받도록 고쳐 두어야 한다
        # (bringup_robot.launch.xml 의 push-ros-namespace 절차). 그 수정 전
        # 로봇에서는 이 인자가 무시되고 /odom·/scan 이 루트에 남는다.
        IncludeLaunchDescription(
            AnyLaunchDescriptionSource(vendor_bringup),
            launch_arguments={'namespace': namespace}.items(),
        ),
        # 실기 OMX endpoint는 검증 전 motion을 내보내지 않는 skeleton으로만 포함한다.
        # 정거장은 로봇에 속하지 않으므로 namespace 밖에 둔다.
        Node(package='trihouse_omx_adapter', executable='hardware_omx_adapter', parameters=[{'omx_id': omx_station_id}]),
    ])
