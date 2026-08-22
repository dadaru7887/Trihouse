"""실기 Pinky launch 가 벤더 nav2 에 넘기는 계약.

시뮬은 `nav2_bringup` 이라 `RewrittenYaml(root_key=namespace)` 가 최상위 키를 감싸
주지만, 실기는 벤더 `pinky_navigation/launch/bringup_launch.xml` 이고 그것은
`<param from>` 으로 원본을 그대로 넘긴다. 그리고 벤더 params 의 최상위 키는 `amcl:`
같은 맨 이름이고 `/**:` 와일드카드가 없다. 그래서 `/pinky_01/amcl` 노드와 매칭되지
않아 파라미터가 한 개도 적용되지 않는다.
"""

import importlib.util
import sys
from pathlib import Path

from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription
from launch_ros.actions import Node, SetRemap

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "launch" / "trihouse_pinky.launch.py"

sys.path.insert(0, str(ROOT))


def _module():
    spec = importlib.util.spec_from_file_location("trihouse_pinky_launch", LAUNCH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _flatten(entities):
    for entity in entities:
        yield entity
        if isinstance(entity, GroupAction):
            yield from _flatten(entity.get_sub_entities())


def _remap(entity):
    """`SetRemap` 은 src/dst 를 비공개 이름으로 들고 있고 그 이름은 배포판마다 다르다."""
    def literal(parts):
        return "".join(part.text for part in parts)

    return (
        literal(getattr(entity, "_SetRemap__src")),
        literal(getattr(entity, "_SetRemap__dst")),
    )


def _declared_arguments(description):
    return {
        action.name
        for action in description.entities
        if isinstance(action, DeclareLaunchArgument)
    }


def test_launch_declares_the_nav2_params_file_argument() -> None:
    """벤더 XML 은 RewrittenYaml 을 쓰지 않으므로 감싼 params 를 우리가 넘겨야 한다."""
    description = _module().generate_launch_description()

    assert "nav2_params_file" in _declared_arguments(description)


def test_the_nav2_params_argument_defaults_to_the_vendor_file() -> None:
    """분기 B(namespace 없이 단일 로봇)에서는 벤더 기본 params 가 그대로 맞다."""
    description = _module().generate_launch_description()
    declared = {
        action.name: action
        for action in description.entities
        if isinstance(action, DeclareLaunchArgument)
    }

    assert declared["nav2_params_file"].default_value[0].text == ""


def test_vendor_bringup_is_wrapped_in_a_tf_remap_group() -> None:
    """벤더 발행자의 TF 를 nav2 가 듣는 자리로 옮긴다.

    벤더 navigation XML 이 nav2 노드에 `/tf -> tf` 를 걸어 두어 nav2 는
    `/pinky_01/tf` 를 듣는다. 발행자(robot_state_publisher, odom)가 루트에 남으면
    AMCL 이 스캔을 전량 폐기한다 — 시뮬에서 확인한 것과 같은 실패다.
    """
    description = _module().generate_launch_description()
    remapped = {
        _remap(entity)
        for entity in _flatten(description.entities)
        if isinstance(entity, SetRemap)
    }

    assert ("/tf", "tf") in remapped
    assert ("/tf_static", "tf_static") in remapped


def test_the_vendor_bringup_is_not_pushed_into_the_namespace_twice() -> None:
    """벤더 bringup 은 자기 인자로 스스로 push 한다. 또 감싸면 `/pinky_01/pinky_01/...` 이 된다."""
    module = _module()
    description = module.generate_launch_description()
    tf_groups = [
        entity
        for entity in description.entities
        if isinstance(entity, GroupAction)
        and any(
            isinstance(child, SetRemap) and _remap(child)[0] == "/tf"
            for child in entity.get_sub_entities()
        )
    ]

    assert len(tf_groups) == 1
    from launch_ros.actions import PushRosNamespace

    assert not any(
        isinstance(child, PushRosNamespace)
        for child in _flatten(tf_groups[0].get_sub_entities())
    )


def test_vision_is_included_so_the_camera_reaches_mediamtx() -> None:
    """카메라는 ROS 를 거치지 않는다 — `camera_streamer` 가 ffmpeg 로 RTSP 를 민다.

    `vision_enabled` 를 선언만 하고 쓰지 않으면 실기에서 스트림이 아예 생기지
    않고, 서버의 QR·ArUco 인식이 받을 것이 없다.
    """
    description = _module().generate_launch_description()
    locations = [
        str(entity.launch_description_source.location)
        for entity in _flatten(description.entities)
        if isinstance(entity, IncludeLaunchDescription)
    ]

    assert any("vision.launch.py" in location for location in locations)


def test_launch_declares_the_vision_config_argument() -> None:
    description = _module().generate_launch_description()

    assert "vision_config_file" in _declared_arguments(description)


def test_the_vision_config_defaults_to_a_real_file_not_an_empty_string() -> None:
    """빈 문자열을 넘기면 `camera_streamer` 가 그것을 params 파일로 읽으려다 죽는다.

    `DeclareLaunchArgument` 의 기본값은 인자를 **주지 않았을 때만** 쓰인다.
    `config_file=''` 를 명시적으로 넘기면 vision launch 의 기본값이 적용되지 않는다.
    """
    from launch import LaunchContext

    description = _module().generate_launch_description()
    declared = {
        action.name: action
        for action in description.entities
        if isinstance(action, DeclareLaunchArgument)
    }
    context = LaunchContext()

    resolved = "".join(
        part.perform(context) for part in declared["vision_config_file"].default_value
    )

    assert resolved.endswith(".yaml")
    assert Path(resolved).is_file()


def test_vision_stays_inside_the_robot_namespace() -> None:
    """두 로봇의 카메라 노드가 섞이지 않도록 namespace 안에 둔다."""
    module = _module()
    description = module.generate_launch_description()
    from launch_ros.actions import PushRosNamespace

    namespaced = [
        entity
        for entity in description.entities
        if isinstance(entity, GroupAction)
        and any(
            isinstance(child, PushRosNamespace)
            for child in entity.get_sub_entities()
        )
    ]
    included = [
        str(entity.launch_description_source.location)
        for group in namespaced
        for entity in _flatten(group.get_sub_entities())
        if isinstance(entity, IncludeLaunchDescription)
    ]

    assert any("vision.launch.py" in location for location in included)


def test_marker_docking_is_wired_inside_the_robot_namespace() -> None:
    description = _module().generate_launch_description()
    arguments = _declared_arguments(description)
    assert {"marker_docks_file", "narrow_zones_file", "narrow_map_name"} <= arguments

    nodes = [entity for entity in _flatten(description.entities) if isinstance(entity, Node)]
    assert any(
        str(node.node_package) == "trihouse_pinky_docking"
        and str(node.node_executable) == "marker_dock"
        for node in nodes
    )


def test_narrow_calibration_is_an_explicit_launch_argument() -> None:
    description = _module().generate_launch_description()
    declared = {
        action.name: action
        for action in description.entities
        if isinstance(action, DeclareLaunchArgument)
    }

    assert "allow_narrow_calibration" in declared
    assert declared["allow_narrow_calibration"].default_value[0].text == "false"


def test_mobile_robot_bringup_does_not_start_an_omx_station_adapter() -> None:
    """OMX 정거장은 별도 장비에서 실행되며 Pinky 기동을 막아서는 안 된다."""
    description = _module().generate_launch_description()
    nodes = [entity for entity in _flatten(description.entities) if isinstance(entity, Node)]

    assert not any(
        str(node.node_package) == "trihouse_omx_adapter"
        for node in nodes
    )
