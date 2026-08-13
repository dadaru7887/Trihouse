"""control_system overlay와 Trihouse runtime을 단일 소유권으로 조합한다."""

from pathlib import Path

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    GroupAction,
    IncludeLaunchDescription,
    OpaqueFunction,
    TimerAction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def _safe_path_token(value: str) -> str:
    token = "".join(
        character if character.isalnum() or character in ("-", "_") else "_"
        for character in value.strip("/")
    ).strip("_")
    if not token:
        raise RuntimeError("robot_namespace는 안전한 경로 토큰을 포함해야 합니다")
    return token


def _include(path: Path, arguments: dict, condition=None):
    return IncludeLaunchDescription(
        AnyLaunchDescriptionSource(str(path)),
        launch_arguments=arguments.items(),
        condition=condition,
    )


def _runtime(context):
    rmf_ws_root = Path(
        LaunchConfiguration("rmf_ws_root").perform(context)
    ).expanduser().resolve()
    if not (rmf_ws_root / "install").is_dir():
        raise RuntimeError(
            f"Open-RMF workspace install이 없습니다: {rmf_ws_root / 'install'}"
        )
    control_root = Path(
        LaunchConfiguration("control_system_root").perform(context)
    ).expanduser().resolve()
    runtime_state_root = Path(
        LaunchConfiguration("runtime_state_root").perform(context)
    ).expanduser().resolve()
    if runtime_state_root == control_root or control_root in runtime_state_root.parents:
        raise RuntimeError(
            "runtime_state_root는 불변 control_system_root 외부여야 합니다"
        )
    runtime_state_root.mkdir(parents=True, exist_ok=True)
    project = LaunchConfiguration("project_name").perform(context)
    project_dir = control_root / "rmf_maps" / project
    if not project_dir.is_dir():
        raise RuntimeError(f"control_system RMF project가 없습니다: {project_dir}")

    core_launch = project_dir / f"{project}.launch.xml"
    gazebo_launch = project_dir / f"{project}_bringup.launch.xml"
    nav2_launch = project_dir / f"{project}_nav2.launch.xml"
    for path in (core_launch, gazebo_launch, nav2_launch):
        if not path.is_file():
            raise RuntimeError(f"필수 control_system launch가 없습니다: {path}")
    nav_graph = project_dir / "nav_graphs" / "0.yaml"
    if not nav_graph.is_file():
        raise RuntimeError(
            f"RMF nav graph가 없습니다: {nav_graph}. "
            "control_system UI에서 project를 다시 export하세요."
        )
    if "nav2_adapter.py" in nav2_launch.read_text(encoding="utf-8"):
        raise RuntimeError(
            "기존 project Nav2 adapter가 남아 있습니다. "
            "prepare_control_system_overlay 실행 파일로 test overlay를 만드세요."
        )

    use_sim_time = LaunchConfiguration("use_sim_time")
    robot_id = LaunchConfiguration("robot_id")
    robot_namespace = LaunchConfiguration("robot_namespace")
    map_revision = LaunchConfiguration("map_revision")
    control_host = LaunchConfiguration("control_host")
    control_port = LaunchConfiguration("control_port")
    map_dir_args = {
        "map_dir": str(project_dir),
        "use_sim_time": use_sim_time,
    }
    robot_prefix = f"/{robot_namespace.perform(context).strip('/')}"
    robot_status_topic = f"{robot_prefix}/trihouse/status"
    transport_action = f"{robot_prefix}/trihouse/transport/execute"
    trihouse_topics = (
        "/trihouse/battery",
        "/trihouse/battery/condition",
        "/trihouse/battery/policy_state",
        "/trihouse/readiness",
        "/trihouse/fms/state",
        "/trihouse/fms/event_outbox_ready",
        "/trihouse/safety/state",
        "/trihouse/safety/emergency_request",
        "/trihouse/safety/keep_out_zones",
        "/trihouse/safety/clear_emergency",
        "/trihouse/status",
        "/trihouse/navigation/state",
        "/trihouse/task/events",
        "/trihouse/transport/execute",
        "/trihouse/cargo/state",
        "/trihouse/health",
        "/trihouse/display/destination_code",
        "/trihouse/indicator/state",
        "/trihouse/proximity/front",
        "/trihouse/vision/person_detection/base",
    )
    trihouse_remaps = [
        (topic, f"{robot_prefix}{topic}") for topic in trihouse_topics
    ]
    sensor_remaps = [
        ("/scan", f"{robot_prefix}/scan"),
        ("/odom", f"{robot_prefix}/odom"),
        ("/amcl_pose", f"{robot_prefix}/amcl_pose"),
    ]
    navigation_remaps = [
        *sensor_remaps,
        ("/navigate_to_pose", f"{robot_prefix}/navigate_to_pose"),
    ]

    actions = [
        _include(
            core_launch,
            {**map_dir_args, "headless": LaunchConfiguration("headless")},
            IfCondition(LaunchConfiguration("start_control_system_core")),
        ),
        _include(
            gazebo_launch,
            {"map_dir": str(project_dir), "headless": LaunchConfiguration("headless")},
            IfCondition(LaunchConfiguration("start_gazebo")),
        ),
        _include(
            nav2_launch,
            map_dir_args,
            IfCondition(LaunchConfiguration("start_nav2")),
        ),
    ]

    edge_nodes = [
        Node(
            package="trihouse_pinky_bringup", executable="sim_hardware",
            name="trihouse_sim_hardware", output="screen",
            parameters=[{
                "use_sim_time": use_sim_time,
                "battery_percentage": ParameterValue(
                    LaunchConfiguration("battery_percentage"), value_type=float,
                ),
                "charging": ParameterValue(
                    LaunchConfiguration("charging"), value_type=bool,
                ),
                "discharge_percent_per_second": ParameterValue(
                    LaunchConfiguration("discharge_percent_per_second"), value_type=float,
                ),
            }], remappings=trihouse_remaps,
        ),
        Node(
            package="trihouse_pinky_safety", executable="safety_supervisor",
            output="screen", parameters=[{
                "robot_id": robot_id, "use_sim_time": use_sim_time,
                "require_ultrasonic": False,
            }],
            remappings=[
                *trihouse_remaps,
                *sensor_remaps,
                ("/cmd_vel_nav", f"{robot_prefix}/cmd_vel_nav"),
                ("/cmd_vel", f"{robot_prefix}/cmd_vel"),
            ],
        ),
        Node(
            package="trihouse_pinky_bringup", executable="readiness_checker",
            output="screen", parameters=[{
                "robot_id": robot_id, "use_sim_time": use_sim_time,
            }], remappings=[*trihouse_remaps, *navigation_remaps],
        ),
        Node(
            package="trihouse_pinky_fleet", executable="battery_condition",
            output="screen", parameters=[{
                "robot_id": robot_id, "use_sim_time": use_sim_time,
            }], remappings=trihouse_remaps,
        ),
        Node(
            package="trihouse_pinky_fleet", executable="battery_policy",
            output="screen", parameters=[{"use_sim_time": use_sim_time}],
            remappings=trihouse_remaps,
        ),
        Node(
            package="trihouse_pinky_fleet", executable="status_node",
            output="screen", parameters=[{
                "robot_id": robot_id, "map_revision": map_revision,
                "use_sim_time": use_sim_time,
            }], remappings=[*trihouse_remaps, *sensor_remaps],
        ),
        Node(
            package="trihouse_pinky_fleet", executable="recovery_health",
            output="screen", parameters=[{
                "robot_id": robot_id, "use_sim_time": use_sim_time,
            }], remappings=[*trihouse_remaps, *sensor_remaps],
        ),
        Node(
            package="trihouse_pinky_fleet", executable="fleet_node",
            output="screen", parameters=[{
                "robot_id": robot_id, "map_revision": map_revision,
                "use_sim_time": use_sim_time,
            }], remappings=[*trihouse_remaps, *navigation_remaps],
        ),
        Node(
            package="trihouse_pinky_fleet", executable="fleet_gateway",
            output="screen", parameters=[{
                "robot_id": robot_id, "control_host": control_host,
                "control_port": control_port, "use_sim_time": use_sim_time,
                "event_outbox_max_pending": ParameterValue(
                    LaunchConfiguration("event_outbox_max_pending"), value_type=int,
                ),
                "event_outbox_path": str(
                    runtime_state_root /
                    f"{_safe_path_token(robot_namespace.perform(context))}_task_events.sqlite3"
                ),
            }], remappings=trihouse_remaps,
        ),
    ]
    adapter = _include(
        Path(__file__).with_name("pinky_easy_fleet_adapter.launch.py"),
        {
            "config_file": LaunchConfiguration("fleet_config"),
            "nav_graph": str(nav_graph),
            "robot_name": robot_id,
            "rmf_map_name": LaunchConfiguration("rmf_map_name"),
            "charger_waypoint": LaunchConfiguration("charger_waypoint"),
            "map_revision": map_revision,
            "fms_base_url": LaunchConfiguration("fms_base_url"),
            "robot_status_topic": robot_status_topic,
            "transport_action": transport_action,
            "use_sim_time": use_sim_time,
        },
        IfCondition(LaunchConfiguration("start_trihouse_adapter")),
    )
    rmf_worker = ExecuteProcess(
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
                ":",
                EnvironmentVariable("PYTHONPATH", default_value=""),
            ]
        },
        output="screen",
        condition=IfCondition(LaunchConfiguration("start_rmf_worker")),
    )
    actions.append(TimerAction(
        period=LaunchConfiguration("startup_delay_s"),
        actions=[
            GroupAction(
                actions=edge_nodes,
                condition=IfCondition(LaunchConfiguration("start_pinky_runtime")),
            ),
            adapter,
            rmf_worker,
        ],
    ))
    return actions


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        DeclareLaunchArgument("control_system_root"),
        DeclareLaunchArgument("runtime_state_root"),
        DeclareLaunchArgument("trihouse_root"),
        DeclareLaunchArgument("rmf_ws_root"),
        DeclareLaunchArgument("project_name", default_value="project1"),
        DeclareLaunchArgument("robot_id", default_value="PK_01"),
        DeclareLaunchArgument("robot_namespace", default_value="pinky_01"),
        DeclareLaunchArgument("rmf_map_name", default_value="L1"),
        DeclareLaunchArgument("charger_waypoint", default_value="충전1"),
        # 운영자가 publish artifact의 content hash를 명시해야 한다. 날짜나 경로를
        # revision처럼 자동 생성하면 서로 다른 지도가 같은 작업 문맥을 공유한다.
        DeclareLaunchArgument("map_revision"),
        DeclareLaunchArgument("fleet_config"),
        DeclareLaunchArgument("fleet_name", default_value="project1_pinky"),
        DeclareLaunchArgument("rmf_worker_id", default_value="trihouse-rmf-worker"),
        DeclareLaunchArgument("fms_base_url", default_value="http://127.0.0.1:8080"),
        DeclareLaunchArgument("control_host", default_value="127.0.0.1"),
        DeclareLaunchArgument("control_port", default_value="8788"),
        DeclareLaunchArgument("event_outbox_max_pending", default_value="1000"),
        DeclareLaunchArgument("use_sim_time", default_value="true"),
        DeclareLaunchArgument("headless", default_value="true"),
        DeclareLaunchArgument("start_control_system_core", default_value="true"),
        DeclareLaunchArgument("start_gazebo", default_value="true"),
        DeclareLaunchArgument("start_nav2", default_value="true"),
        DeclareLaunchArgument("start_pinky_runtime", default_value="true"),
        DeclareLaunchArgument("start_trihouse_adapter", default_value="true"),
        DeclareLaunchArgument("start_rmf_worker", default_value="true"),
        DeclareLaunchArgument("startup_delay_s", default_value="5.0"),
        DeclareLaunchArgument("battery_percentage", default_value="1.0"),
        DeclareLaunchArgument("charging", default_value="false"),
        DeclareLaunchArgument("discharge_percent_per_second", default_value="0.0"),
        OpaqueFunction(function=_runtime),
    ])
