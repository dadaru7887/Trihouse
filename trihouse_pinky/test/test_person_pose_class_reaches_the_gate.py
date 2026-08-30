"""카메라가 붙여 보낸 자세 상태가 주행 판단까지 실제로 도달하는가.

정책만 고치고 node 가 값을 안 넘기면 그 정책은 죽은 코드다. 증상은 예외가
아니라 "쓰러진 사람 앞에서 로봇이 계속 간다" 로 나타난다.
"""

import ast
import sys
import unittest
from pathlib import Path

SAFETY = Path(__file__).resolve().parents[1] / "trihouse_pinky_safety"
sys.path.insert(0, str(SAFETY))

NODE = SAFETY / "trihouse_pinky_safety" / "safety_supervisor_node.py"


def _tree() -> ast.Module:
    return ast.parse(NODE.read_text(encoding="utf-8"))


class PoseClassWiringTest(unittest.TestCase):
    def test_the_person_callback_keeps_the_pose_class(self) -> None:
        """`_on_person` 이 message.pose_class 를 실제로 읽어야 한다."""
        source = NODE.read_text(encoding="utf-8")
        callback = source[source.index("def _on_person"):source.index("def _on_keep_out")]

        self.assertIn("pose_class", callback)

    def test_the_gate_is_given_the_pose_class(self) -> None:
        """SafetyInputs(...) 호출에 person_pose_class 인자가 있어야 한다."""
        for node in ast.walk(_tree()):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "SafetyInputs"):
                keywords = {keyword.arg for keyword in node.keywords}
                self.assertIn("person_pose_class", keywords)
                return
        self.fail("SafetyInputs 호출을 찾지 못했습니다")

    def test_a_stale_observation_does_not_keep_a_stale_pose_class(self) -> None:
        """TTL 이 지난 관측의 자세를 계속 들고 있으면 안 된다.

        person_detected 는 이미 TTL 로 꺼지는데 pose_class 만 남으면, 사람이
        사라진 뒤에도 "쓰러짐" 이 붙은 채로 판단에 들어갈 수 있다.
        """
        source = NODE.read_text(encoding="utf-8")
        call = source[source.index("inputs = SafetyInputs("):source.index("decision = apply_safety_gate")]
        line = [row for row in call.splitlines() if "person_pose_class" in row]

        self.assertTrue(line, "person_pose_class 인자가 없습니다")
        self.assertIn("person_detected", line[0],
                      "person_detected 로 걸러진 값이어야 합니다")
