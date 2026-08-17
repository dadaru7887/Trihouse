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


class SimulationStatusPathContractTest(unittest.TestCase):
    """P0 시뮬레이션에서 status_node 의 양 끝이 실제로 이어지는지 확인한다.

    `two_pinky_order_demo.launch.py` 는 `status_node` 를
    `PushRosNamespace(namespace)` 그룹 안에서 띄우고, fleet adapter 에게는
    `/<namespace>/trihouse/status` 를 읽으라고 알려 준다. 토픽 remap 은 TF 두
    개뿐이다(nav2 가 TF 를 로봇 namespace 안에서 주고받기 때문이며, 아래
    `test_status_node_gets_tf_where_nav2_publishes_it` 가 그것을 지킨다). 그래서
    `status_node` 가 토픽을 절대 이름으로 적으면 namespace 가 통째로 무시되어
    양쪽이 어긋난다 — 노드는 루트에 발행하고 adapter 는 namespace 아래를
    듣는다. 입력도 마찬가지로 gz bridge 는 `<namespace>/odom` 을 내보내는데
    노드는 루트 `/odom` 을 구독하게 된다.

    그러면 RMF 는 로봇의 위치와 상태를 영영 받지 못하고, 주문은 navigate 단계에서
    조용히 멈춘다. 오류도 경고도 나지 않기 때문에 테스트로 고정한다.
    """

    DEMO_LAUNCH = REPO / "trihouse_rmf_bridge/launch/two_pinky_order_demo.launch.py"
    STATUS_NODE = (
        REPO / "trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/status_node.py"
    )

    def test_fleet_adapter_reads_the_namespaced_status_topic(self) -> None:
        source = self.DEMO_LAUNCH.read_text(encoding="utf-8")

        self.assertIn('"robot_status_topic": f"/{namespace}/trihouse/status"', source)

    def test_status_node_publishes_where_the_adapter_listens(self) -> None:
        names = dict.fromkeys(name for _line, name in _declared_names(self.STATUS_NODE))

        # 상대 이름이어야 PushRosNamespace 가 `/pinky_01/trihouse/status` 로 만든다.
        self.assertIn("trihouse/status", names)
        self.assertNotIn("/trihouse/status", names)

    def test_status_node_reads_the_namespaced_sensor_topics(self) -> None:
        names = dict.fromkeys(name for _line, name in _declared_names(self.STATUS_NODE))

        for relative in ("odom", "scan"):
            with self.subTest(topic=relative):
                self.assertIn(relative, names)
                self.assertNotIn(f"/{relative}", names)

    def test_status_node_takes_the_map_pose_from_tf_not_from_amcl_pose(self) -> None:
        """`amcl_pose` 를 신선도의 근거로 쓰면 정지한 로봇이 영영 못 움직인다.

        nav2 AMCL 은 `amcl_pose` 를 이벤트로만 낸다 — 첫 스캔에 한 번, 그 뒤로는
        로봇이 `update_min_d` 만큼 움직여 재표집될 때만이다. 그래서 그 토픽의
        신선도는 위치추정이 살아 있는지가 아니라 로봇이 움직였는지를 잰다.

        충전기에 세워 둔 로봇은 이렇게 막힌다. amcl_pose 가 한 번 오고 timeout 이
        지나 `map_pose_stale` 이 되면 frame_id 가 odom 으로 떨어지고, adapter 는
        frame_id 가 `map` 이 아닌 로봇을 거부하고, 그러면 job 이 배정되지 않아
        로봇은 움직이지 않고, 움직이지 않으니 amcl_pose 도 다시 오지 않는다.

        AMCL 이 지속적으로 내보내는 것은 `map -> odom` 변환이다. 그것을 보면
        위치추정이 지금 살아 있는지를 그대로 알 수 있고, 최신 odometry 까지
        합성된 pose 를 얻는다. nav2 자신의 소비자(costmap, controller)도 모두
        TF 를 본다.
        """
        source = self.STATUS_NODE.read_text(encoding="utf-8")
        names = dict.fromkeys(name for _line, name in _declared_names(self.STATUS_NODE))

        self.assertNotIn("amcl_pose", names)
        self.assertIn("TransformListener", source)
        self.assertIn("lookup_transform", source)

    def test_status_node_gets_tf_where_nav2_publishes_it(self) -> None:
        """TF 는 이제 로봇 namespace 안에 있다.

        nav2_bringup 이 자기 노드 전부에 `[('/tf','tf'), ('/tf_static','tf_static')]`
        을 걸어 두어서 AMCL 은 `/<namespace>/tf` 로 방송한다. status_node 가 루트
        `/tf` 를 들으면 아무것도 받지 못하므로 같은 remap 을 받아야 한다.
        """
        source = self.DEMO_LAUNCH.read_text(encoding="utf-8")
        # status_node 항목은 그룹의 마지막이라 `return GroupAction` 이 그 끝이다.
        # `),` 로 자르면 remappings 튜플 안에서 끊긴다.
        block = source.split('executable="status_node"', 1)[1].split(
            "return GroupAction", 1
        )[0]

        self.assertIn('("/tf", "tf")', block)
        self.assertIn('("/tf_static", "tf_static")', block)
        # 프레임 이름에는 로봇 접두사가 붙어 있다(robot_state_publisher 의
        # `frame_prefix`). 노드가 그 이름을 알아야 조회가 성립한다.
        self.assertIn('f"{namespace}/base_footprint"', block)

    def test_gazebo_bridge_topics_stay_relative_so_they_get_the_prefix(self) -> None:
        # 브리지는 `f"{namespace}/{topic}"` 으로 접두사를 직접 붙인다. 여기에
        # `/` 로 시작하는 이름이 들어가면 `pinky_01//odom` 이 된다.
        source = self.DEMO_LAUNCH.read_text(encoding="utf-8")
        block = source.split("ROBOT_BRIDGE_TOPICS = (", 1)[1].split(")", 1)[0]

        for entry in block.splitlines():
            stripped = entry.strip().strip(",").strip('"')
            if not stripped:
                continue

            self.assertFalse(stripped.startswith("/"), stripped)


if __name__ == "__main__":
    unittest.main()
