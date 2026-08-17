"""Gazebo launch의 배터리 시나리오 제어 계약 테스트."""

import importlib.util
from pathlib import Path

from launch.actions import DeclareLaunchArgument
from launch_ros.actions import Node


LAUNCH_PATH = (
    Path(__file__).resolve().parents[1]
    / "trihouse_pinky_bringup"
    / "launch"
    / "trihouse_pinky_sim.launch.py"
)


def _description():
    spec = importlib.util.spec_from_file_location(
        "trihouse_pinky_sim_launch", LAUNCH_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.generate_launch_description()


def test_sim_launch_exposes_battery_scenario_controls() -> None:
    """실행 시 초기 SOC·충방전률을 바꿀 수 없는 회귀를 막는다."""
    description = _description()
    names = {
        action.name
        for action in description.entities
        if isinstance(action, DeclareLaunchArgument)
    }

    assert {
        "battery_percentage",
        "charging",
        "charge_percent_per_second",
        "discharge_percent_per_second",
    } <= names



def _all_nodes(entities):
    """GroupAction 안까지 훑는다.

    onboard 노드는 이제 `PushRosNamespace` 를 적용하는 GroupAction 안에 들어
    있으므로 최상위 entities 만 보면 찾지 못한다. 로봇 구분이 namespace 로
    바뀐 결과이지 노드가 사라진 것이 아니다.
    """
    for entity in entities:
        if isinstance(entity, Node):
            yield entity
        else:
            children = getattr(entity, "get_sub_entities", None)
            if children is not None:
                yield from _all_nodes(children())

def test_sim_hardware_receives_all_battery_controls() -> None:
    """선언된 launch 인자가 sim_hardware parameter로 전달되지 않는 회귀를 막는다."""
    description = _description()
    sim_hardware = next(
        action
        for action in _all_nodes(description.entities)
        if action.node_executable == "sim_hardware"
    )
    parameters = sim_hardware._Node__parameters[0]
    names = {key[0].text for key in parameters}

    assert {
        "battery_percentage",
        "charging",
        "charge_percent_per_second",
        "discharge_percent_per_second",
    } <= names
