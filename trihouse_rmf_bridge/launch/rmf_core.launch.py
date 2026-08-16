"""Open-RMF core. fleet adapter 가 붙기 전에 반드시 먼저 떠야 한다.

`control_system/rmf_maps/project1/project1.launch.xml` 이 검증한 구성을 그대로
옮겼다. `rmf_demos` 의 `common.launch.xml` 을 include 하지 않는 이유도 같다.
그 파일은 시각화 Lane 굵기·글자 크기를 밖에서 못 바꾸게 막아 두어, 2~3 m 짜리
도면에서 Lane 하나가 건물 폭의 1/5 로 그려진다.

여기서는 P0 에 필요한 노드만 띄운다.

- `rmf_traffic_schedule` / `rmf_traffic_blockade`: 교통 일정과 차단
- `door_supervisor` / `lift_supervisor` / `mutex_group_supervisor`
- `rmf_task_dispatcher`: 작업 입찰

`building_map_server` 와 RViz 는 프로젝트별 산출물(`*.building.yaml`, `*.rviz`)
이 있어야 하므로 인자로 경로를 주었을 때만 띄운다. P0 시뮬레이션은 Nav2 지도를
쓰므로 기본값은 꺼져 있다.
"""

from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, OpaqueFunction
from launch.conditions import IfCondition
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.actions import IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, SetParameter


def _core(context):
    use_sim_time = LaunchConfiguration("use_sim_time")
    sim_time = {"use_sim_time": LaunchConfiguration("use_sim_time")}
    building_map = LaunchConfiguration("building_map_file").perform(context).strip()

    actions = [
        Node(
            package="rmf_traffic_ros2",
            executable="rmf_traffic_schedule",
            name="rmf_traffic_schedule_primary",
            output="both",
            parameters=[sim_time],
        ),
        Node(
            package="rmf_traffic_ros2",
            executable="rmf_traffic_blockade",
            output="both",
            parameters=[sim_time],
        ),
        Node(
            package="rmf_fleet_adapter",
            executable="door_supervisor",
            parameters=[sim_time],
        ),
        Node(
            package="rmf_fleet_adapter",
            executable="lift_supervisor",
            parameters=[sim_time],
        ),
        Node(
            package="rmf_fleet_adapter",
            executable="mutex_group_supervisor",
        ),
        Node(
            package="rmf_task_ros2",
            executable="rmf_task_dispatcher",
            output="screen",
            parameters=[
                sim_time,
                {
                    "bidding_time_window": 2.0,
                    "use_unique_hex_string_with_task_id": True,
                    # rmf-web 을 쓰지 않으면 비워 둔다. 주소를 주면 dispatcher 가
                    # 1초마다 영원히 다시 붙으려 하며 로그를 채운다.
                    "server_uri": LaunchConfiguration("server_uri"),
                },
            ],
        ),
    ]

    if building_map:
        if not Path(building_map).is_file():
            raise RuntimeError(f"building map이 없습니다: {building_map}")
        actions.append(
            Node(
                package="rmf_building_map_tools",
                executable="building_map_server",
                arguments=[building_map],
                parameters=[sim_time],
            )
        )

    # 시각화는 <group> 으로 감싼다. XML launch 의 include 는 스스로 범위를
    # 만들지 않아 인자가 바깥으로 샌다. 여기서도 같은 격리를 유지한다.
    actions.append(
        GroupAction(
            actions=[
                SetParameter(name="trihouse_pinky_radius", value=0.050),
                IncludeLaunchDescription(
                    AnyLaunchDescriptionSource(
                        str(
                            Path(
                                _share("rmf_visualization")
                            )
                            / "visualization.launch.xml"
                        )
                    ),
                    launch_arguments={
                        "use_sim_time": use_sim_time,
                        "map_name": LaunchConfiguration("initial_map"),
                        "lane_width": LaunchConfiguration("lane_width"),
                        "waypoint_scale": LaunchConfiguration("waypoint_scale"),
                        "text_scale": LaunchConfiguration("text_scale"),
                        "headless": "true",
                    }.items(),
                ),
            ],
            condition=IfCondition(LaunchConfiguration("start_visualization")),
        )
    )
    return actions


def _share(package: str) -> str:
    from ament_index_python.packages import get_package_share_directory

    return get_package_share_directory(package)


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument("use_sim_time", default_value="true"),
            DeclareLaunchArgument("server_uri", default_value=""),
            DeclareLaunchArgument("initial_map", default_value="L1"),
            # 창고용 기본값 0.5 m 는 2~3 m 도면에서 Lane 이 뭉쳐 보인다.
            DeclareLaunchArgument("lane_width", default_value="0.120"),
            DeclareLaunchArgument("waypoint_scale", default_value="1.000"),
            DeclareLaunchArgument("text_scale", default_value="0.600"),
            DeclareLaunchArgument("start_visualization", default_value="true"),
            DeclareLaunchArgument("building_map_file", default_value=""),
            OpaqueFunction(function=_core),
        ]
    )
