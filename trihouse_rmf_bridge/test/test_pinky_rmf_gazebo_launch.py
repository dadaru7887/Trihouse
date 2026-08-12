"""Pinky Gazebo와 Open-RMF core/adapter 조합 launch 계약."""

import importlib.util
from pathlib import Path

from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch_ros.actions import Node


BRIDGE_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_LAUNCH = (
    BRIDGE_ROOT / "launch" / "pinky_rmf_gazebo_validation.launch.py"
)
ADAPTER_LAUNCH = BRIDGE_ROOT / "launch" / "pinky_easy_fleet_adapter.launch.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.generate_launch_description()


def test_validation_launch_declares_simulation_and_rmf_core_controls() -> None:
    """Gazebo와 RMF가 서로 다른 clock/core 구성으로 시작되는 회귀를 막는다."""
    description = _load(VALIDATION_LAUNCH, "pinky_rmf_gazebo_validation")
    names = {
        action.name
        for action in description.entities
        if isinstance(action, DeclareLaunchArgument)
    }

    assert {
        "nav_graph",
        "map",
        "use_sim_time",
        "start_rmf_core",
        "battery_percentage",
        "charging",
        "discharge_percent_per_second",
    } <= names


def test_validation_launch_combines_pinky_adapter_schedule_and_dispatcher() -> None:
    """task API만 뜨고 traffic schedule 또는 Fleet Adapter가 없는 회귀를 막는다."""
    description = _load(VALIDATION_LAUNCH, "pinky_rmf_gazebo_nodes")
    includes = [
        action
        for action in description.entities
        if isinstance(action, IncludeLaunchDescription)
    ]
    nodes = [
        action for action in description.entities if isinstance(action, Node)
    ]

    assert len(includes) == 2
    assert any(
        node.node_package == "rmf_traffic_ros2"
        and node.node_executable == "rmf_traffic_schedule"
        for node in nodes
    )
    assert any(
        node.node_package == "rmf_task_ros2"
        and node.node_executable == "rmf_task_dispatcher"
        for node in nodes
    )


def test_easy_adapter_launch_forwards_use_sim_time_to_cli() -> None:
    """Gazebo clock인데 adapter만 wall clock을 사용하는 회귀를 막는다."""
    description = _load(ADAPTER_LAUNCH, "pinky_easy_adapter_sim_time")
    names = {
        action.name
        for action in description.entities
        if isinstance(action, DeclareLaunchArgument)
    }
    adapter = next(
        action
        for action in description.entities
        if isinstance(action, Node)
        and action.node_executable == "pinky_easy_fleet_adapter"
    )

    assert "use_sim_time" in names
    assert "--use-sim-time" in adapter._Node__arguments
