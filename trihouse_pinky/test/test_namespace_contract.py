"""로봇마다 namespace 로 갈라지는 계약을 ROS 설치 없이 점검한다.

실기 Pinky 는 `ros2 launch ... namespace:=pinky_01` 로 뜨고, 벤더 bringup 이
`<push-ros-namespace>` 로 자기 노드를 그 아래에 넣는다. 그래서 실제 로봇의
토픽은 `/pinky_01/odom`, `/pinky_01/scan`, `/pinky_01/cmd_vel` 이다.

`PushRosNamespace` 는 **상대 이름만** 접두사를 붙일 수 있다. 앞에 `/` 가 붙은
절대 이름은 namespace 를 통째로 무시하므로, 노드가 `'/odom'` 이라고 적어 두면
`namespace:=pinky_01` 을 줘도 그 노드는 여전히 루트 `/odom` 을 본다. 실기에서는
그 토픽이 더 이상 존재하지 않으므로 조용히 아무것도 받지 못한다.

따라서 로봇에 속한 토픽은 전부 상대 이름이어야 한다. 이 테스트가 그 규칙을
지킨다. 예외는 여러 로봇이 공유하는 토픽뿐이고, 그 목록은 아래에 명시한다.
"""

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
OMX_ROOT = REPO / "trihouse_omx_adapter"

# 여러 로봇이 함께 쓰는 토픽. namespace 로 가르면 오히려 끊어진다.
#
# `/tf` 와 `/tf_static` 은 여러 로봇이 한 트리를 공유해야 하므로 루트에 둔다
# (구분은 frame_id 의 `pinky_01/` 접두사가 맡는다). `/trihouse/handover/state`
# 는 OMX 정거장이 발행하고 Pinky 가 구독하는 로봇 간 경계 토픽이며,
# `control_system_rmf.launch.py` 의 per-robot remap 목록에도 의도적으로 빠져
# 있다. 그 launch 가 이 구분의 정본이고 여기서 규칙을 새로 만들지 않는다.
SHARED_ABSOLUTE_NAMES = frozenset({
    "/tf",
    "/tf_static",
    "/clock",
    "/map",
    "/trihouse/handover/state",
})

# 토픽/서비스 이름이 몇 번째 인자인지. rclpy 시그니처를 따른다.
_TOPIC_ARGUMENT_INDEX = {
    "create_subscription": 1,
    "create_publisher": 1,
    "create_service": 1,
    "create_client": 1,
    "ActionClient": 2,
    "ActionServer": 2,
}


def _node_sources() -> list[Path]:
    sources = [
        path
        for path in ROOT.rglob("*.py")
        if "/test" not in str(path) and path.name != "setup.py"
    ]
    sources += [
        path for path in OMX_ROOT.rglob("*.py") if "/test" not in str(path)
    ]
    assert sources, "no node sources were discovered"
    return sorted(sources)


def _declared_names(path: Path) -> list[tuple[int, str]]:
    """소스에서 토픽/서비스/액션 이름 리터럴을 뽑는다."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        name = (
            function.attr
            if isinstance(function, ast.Attribute)
            else function.id
            if isinstance(function, ast.Name)
            else None
        )
        index = _TOPIC_ARGUMENT_INDEX.get(name)
        if index is None or len(node.args) <= index:
            continue
        argument = node.args[index]
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            found.append((argument.lineno, argument.value))
    return found


class NamespaceTopicNameContractTest(unittest.TestCase):
    def test_robot_topics_are_relative_so_push_ros_namespace_can_prefix_them(self) -> None:
        offenders: list[str] = []
        for path in _node_sources():
            for line, name in _declared_names(path):
                if not name.startswith("/"):
                    continue
                if name in SHARED_ABSOLUTE_NAMES:
                    continue
                offenders.append(f"{path.relative_to(REPO)}:{line} {name}")

        self.assertEqual(
            [],
            offenders,
            "절대 이름은 PushRosNamespace 를 무시한다. 상대 이름으로 바꾸거나, "
            "정말 공유 토픽이면 SHARED_ABSOLUTE_NAMES 에 근거와 함께 넣어라:\n"
            + "\n".join(offenders),
        )

    def test_shared_topics_stay_absolute(self) -> None:
        # 공유 토픽까지 상대 이름으로 바꿔 버리면 로봇마다 갈라져서
        # OMX 정거장과 TF 트리가 끊어진다. 반대 방향의 실수도 막는다.
        seen: set[str] = set()
        for path in _node_sources():
            for _line, name in _declared_names(path):
                seen.add(name)

        for shared in ("trihouse/handover/state",):
            self.assertNotIn(
                shared,
                seen,
                f"{shared} 는 로봇 간 공유 토픽이므로 절대 이름이어야 한다",
            )


class NamespaceLaunchContractTest(unittest.TestCase):
    """launch 가 `namespace:=pinky_02` 를 받아 실제로 적용하는지 확인한다."""

    LAUNCH_FILES = (
        "trihouse_pinky_bringup/launch/trihouse_pinky.launch.py",
        "trihouse_pinky_bringup/launch/trihouse_pinky_sim.launch.py",
    )

    def test_launch_files_accept_a_namespace_argument(self) -> None:
        for relative in self.LAUNCH_FILES:
            with self.subTest(launch=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")

                self.assertIn("DeclareLaunchArgument('namespace'", source)

    def test_launch_files_apply_the_namespace_to_onboard_nodes(self) -> None:
        for relative in self.LAUNCH_FILES:
            with self.subTest(launch=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")

                self.assertIn("PushRosNamespace", source)

    def test_namespace_default_matches_the_first_robot(self) -> None:
        # 벤더 절차서와 같은 기본값을 쓴다. `robot_id` 는 PK_01, ROS namespace 는
        # pinky_01 로 서로 다른 표기이며 둘을 섞지 않는다.
        source = (ROOT / self.LAUNCH_FILES[0]).read_text(encoding="utf-8")

        self.assertIn("DeclareLaunchArgument('namespace', default_value='pinky_01')", source)


if __name__ == "__main__":
    unittest.main()
