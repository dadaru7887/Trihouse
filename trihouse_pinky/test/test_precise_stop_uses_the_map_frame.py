"""정밀 정차 판정이 odom 을 map 목표와 비교한다 — 그래서 절대 통과하지 못한다.

## 결함

`fleet_node._at_precise_goal` 은 `self.current_pose` 를 목표와 비교한다
(`fleet_node.py:319`, 허용오차 0.05 m / 0.0873 rad). 그런데 `current_pose` 는
`_on_odom` 이 채운다(`fleet_node.py:100`) — **odom 프레임**이다. 반면
`goal.dropoff_pose` 는 **map 프레임**이다(`protocol.py:109` 가 `'map'` 을 박는다).

두 프레임의 원점이 다르므로 비교가 성립하지 않는다. 로봇은 충전 스테이션에서
spawn 하고 odom 은 거기서 0으로 시작하므로, 그 오프셋만큼 언제나 어긋난다.
그리고 odom 은 주행하며 드리프트하므로 오차가 커지기만 한다.

2026-08-19 실측 — 로봇이 냉동 dock 으로 이동한 뒤:

```
odom (판정에 쓰인 값) : (1.158, -1.410)
frozen dock 목표(map) : (1.201, -0.799)      y 가 0.61 m 차이
허용오차              : 0.05 m
```

`pinky_adapter_node.py:242` 가 dock 목적지에 `requires_precise_stop=True` 를 걸므로
**적재/포장 dock 도착은 구조적으로 실패한다.** 실측에서 step 20 이
`final_outcome_reason_code=GOAL_TOLERANCE_NOT_MET` 으로 죽었다.

## 고치는 방향

로봇은 이미 map 프레임 pose 를 발행한다 — `trihouse/status` 의 `RobotStatus` 가
`frame_id` 와 `pose` 를 함께 담는다(`status_node.py:117`). `verify_robot_status.py`
가 그 값으로 `frame_id=map` 을 판정한다. 그것을 쓰면 새 좌표원을 만들 필요가 없다.

odom 은 계속 필요하다 — `stationary` 판정이 속도를 보기 때문이다. **위치만 옮긴다.**

`frame_id` 가 `map` 이 아닐 때는 판정하지 않는다. AMCL 수렴 전에는 로봇이 자기
위치를 map 으로 말할 수 없고, 그때 통과시키면 엉뚱한 자리에서 인계가 열린다.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "trihouse_pinky_fleet"))

pytest.importorskip("trihouse_interfaces", reason="ROS 메시지가 필요하다")
fleet_node = pytest.importorskip("trihouse_pinky_fleet.fleet_node")


class _Goal:
    """`_at_precise_goal` 이 실제로 만지는 것만 갖는다."""

    class _Pose:
        class _P:
            def __init__(self, x, y):
                self.x, self.y, self.z = x, y, 0.0

        class _O:
            x = y = z = 0.0
            w = 1.0

        def __init__(self, x, y):
            self.position = _Goal._Pose._P(x, y)
            self.orientation = _Goal._Pose._O()

    def __init__(self, x, y):
        self.dropoff_pose = type("_S", (), {"pose": _Goal._Pose(x, y)})()


class _Node:
    """map pose 와 odom pose 를 따로 갖는 대역."""

    def __init__(self, *, map_pose, map_frame="map"):
        self.map_pose = map_pose
        self.map_frame = map_frame
        # odom 은 spawn 오프셋만큼 어긋난 값. 실측과 같은 모양이다.
        self.current_pose = (1.158, -1.410, 0.0)

    def _at_precise_goal(self, goal):
        return fleet_node.FleetNode._at_precise_goal(self, goal)


def test_arriving_at_the_dock_passes_when_the_map_pose_matches() -> None:
    """map 으로 보면 도착했다. odom 으로 보면 0.61 m 벗어난다."""
    node = _Node(map_pose=(1.201, -0.799, 0.0))

    assert node._at_precise_goal(_Goal(1.201, -0.799)) is True


def test_a_real_miss_still_fails() -> None:
    """허용오차를 넘으면 map 으로 봐도 실패해야 한다. 판정을 없애는 게 아니다."""
    node = _Node(map_pose=(1.201, -0.500, 0.0))

    assert node._at_precise_goal(_Goal(1.201, -0.799)) is False


def test_no_verdict_before_the_robot_can_speak_in_map() -> None:
    """AMCL 수렴 전에는 통과시키지 않는다. 엉뚱한 자리에서 인계가 열린다."""
    node = _Node(map_pose=(1.201, -0.799, 0.0), map_frame="pinky_01/odom")

    assert node._at_precise_goal(_Goal(1.201, -0.799)) is False


def test_no_verdict_without_a_map_pose_at_all() -> None:
    node = _Node(map_pose=None)

    assert node._at_precise_goal(_Goal(1.201, -0.799)) is False
