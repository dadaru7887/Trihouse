"""쓰러진 사람에 대한 주행 정책. ROS 없이 도는 순수 정책 시험.

`policy.py` 는 dataclass 와 enum 뿐이라 rclpy 없이 import 된다. 같은 판단을
`test_pinky_sr_policies.py` 에 두면 그 파일이 fleet_node 를 거쳐 rclpy 를
끌어오는 탓에 ROS 환경 밖에서는 한 줄도 확인할 수 없다.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "trihouse_pinky_safety"))

from trihouse_pinky_safety.policy import (  # noqa: E402
    MotionCommand, SafetyInputs, SafetyLevel, apply_safety_gate,
)


class FallenPersonSafetyTest(unittest.TestCase):
    """바닥에 쓰러진 사람은 서 있는 사람과 다른 위험이다.

    비켜 줄 수 없고, 라이다 높이에서 잘 안 보이며, 로봇이 향하는 바로 그 바닥에
    있다. 지금까지는 `pose_class` 가 로봇까지 와 놓고 판단에 안 쓰여서, 관제에
    비상 알람이 뜨는 그 순간에도 로봇은 감속만 한 채 그 사람 쪽으로 계속 갔다.
    """

    def _fallen(self, pose_class: str, **overrides):
        values = {
            "person_detected": True,
            "person_distance_m": 0.5,
            "person_pose_class": pose_class,
        }
        values.update(overrides)
        return apply_safety_gate(MotionCommand(0.20, 0.10), SafetyInputs(**values))

    def test_a_standing_person_still_only_slows(self) -> None:
        result = self._fallen("NORMAL")
        self.assertEqual(SafetyLevel.SLOW, result.level)

    def test_a_confirmed_fallen_person_stops_the_robot(self) -> None:
        for pose_class in ("FALLEN", "IMMOBILE", "EMERGENCY_CANDIDATE"):
            with self.subTest(pose_class=pose_class):
                result = self._fallen(pose_class)
                self.assertEqual(SafetyLevel.STOP, result.level)
                self.assertEqual(0.0, result.command.linear_x)
                self.assertEqual(0.0, result.command.angular_z)
                self.assertEqual("person_on_floor", result.reason)

    def test_stopping_for_a_fallen_person_does_not_cancel_the_goal(self) -> None:
        """일어나면 이어서 가야 한다. 임무를 취소하는 것은 사람의 결정이다."""
        self.assertTrue(self._fallen("EMERGENCY_CANDIDATE").goal_may_continue)

    def test_an_unconfirmed_suspicion_only_slows(self) -> None:
        """FALL_SUSPECTED 는 아직 디바운스 전이다.

        창고에서 사람은 수시로 쭈그려 앉는다. 한 프레임짜리 의심마다 급정지하면
        쓸 수 없는 기능이 되고, 쓸 수 없는 안전 기능은 꺼진다.
        """
        result = self._fallen("FALL_SUSPECTED")
        self.assertEqual(SafetyLevel.SLOW, result.level)

    def test_a_fallen_person_outside_the_protective_zone_does_not_stop(self) -> None:
        """방 반대편에 누운 사람 때문에 영영 못 움직이면 안 된다."""
        result = self._fallen("IMMOBILE", person_distance_m=3.0)
        self.assertEqual(SafetyLevel.CLEAR, result.level)

    def test_a_fallen_person_at_unknown_distance_stops(self) -> None:
        """거리를 모르는 것을 안전하다고 읽지 않는다 — 기존 감속 규칙과 같은 방향."""
        result = self._fallen("FALLEN", person_distance_m=None)
        self.assertEqual(SafetyLevel.STOP, result.level)

    def test_an_emergency_latch_still_outranks_a_fallen_person(self) -> None:
        result = apply_safety_gate(
            MotionCommand(0.20, 0.0),
            SafetyInputs(emergency_latched=True, person_detected=True,
                         person_pose_class="EMERGENCY_CANDIDATE"),
        )
        self.assertEqual(SafetyLevel.EMERGENCY, result.level)
