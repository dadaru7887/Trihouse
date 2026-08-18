"""낙찰 결과는 `fleet_states` 로만 돌아온다. `task_summaries` 는 비어 있다. (D20)

## 결함

`RosTaskSummaryObserver.attach()` 가 `task_summaries` 를 구독한다
(`ros_task_client.py:116`). 그런데 이 RMF 배포에서는 **아무도 그 토픽에 발행하지
않는다.** 2026-08-19 04:2x 실측, 12초 구독:

```
task_summaries 수신 : 0
fleet_states  수신 : 97      robot=PK_01  task_id=''  mode=0
```

그래서 낙찰이 원장으로 돌아오지 못한다. 워커는 제출 직후 응답을 받는데 그때는
아직 입찰 전이라 `assignment` 가 없고(정상), 나중에 채워 줄 observer 가 죽은
토픽을 보고 있으니 영원히 `RMF_ASSIGNMENT_PENDING` 이다. 5회 반복 후
`dead_letter` 가 되고 step 은 `failed` 로 멈춘다.

실측으로 확인한 연쇄 — RMF 는 정상적으로 낙찰했고 로봇도 움직였다:

```
Bidding Result: task [compose.dispatch-d79d39763c] is awarded ... expected robot [PK_01]
[PK_01] RMF compose.dispatch-d79d39763c -> (0.841, -0.111, -1.089)
[PK_01] Pinky 도착·정지 확인 후 RMF 이동을 완료했습니다.
RMF dispatch cycle: claimed=1 accepted=0 rejected=0 indeterminate=1   ← 반복
```

**로봇은 움직이는데 원장만 모른다.**

## 무엇을 고정하는가

`fleet_states` 의 `robots[].task_id` 가 비어 있지 않으면 그것이 곧 "이 로봇이 이
작업을 들고 있다" 는 낙찰 사실이다. Gateway 의 `apply_rmf_task_update` 는
`robot_name` 이 오고 메시지가 아직 `sent` 면 그 outbox 를 닫는다
(`repositories.py:5808`). 즉 **이 한 가지 사실만 돌려주면 경로가 이어진다.**

완료·실패는 여기서 만들지 않는다. 그건 로봇 자신이 `task_event` 로 보고하는 경로다.
`fleet_states` 로 성패를 추정하면 취소와 완료를 구분할 수 없다 — 둘 다 `task_id` 가
빈 값으로 돌아가기 때문이다.
"""

import pytest

pytest.importorskip("rmf_fleet_msgs", reason="rclpy/rmf_fleet_msgs 가 필요하다")

from rmf_fleet_msgs.msg import FleetState, RobotMode, RobotState  # noqa: E402

from control_tower.rmf_adapter.task_api import normalize_fleet_state  # noqa: E402


def _fleet(*robots: RobotState, name: str = "project1_pinky") -> FleetState:
    state = FleetState()
    state.name = name
    state.robots = list(robots)
    return state


def _robot(name: str, task_id: str, mode: int) -> RobotState:
    robot = RobotState()
    robot.name = name
    robot.task_id = task_id
    robot.mode = RobotMode(mode=mode)
    return robot


def test_a_robot_holding_a_task_reports_the_assignment() -> None:
    updates = normalize_fleet_state(
        _fleet(_robot("PK_01", "compose.dispatch-d79d39763c", RobotMode.MODE_MOVING)),
        observed_at_ms=1_000,
    )

    assert len(updates) == 1
    update = updates[0]
    assert update.task_id == "compose.dispatch-d79d39763c"
    assert update.robot_name == "PK_01"
    assert update.fleet_name == "project1_pinky"
    assert update.observed_at_ms == 1_000
    # Gateway 는 robot_name 이 오면 outbox 를 닫는다. 그것이 이 경로의 목적이다.
    assert update.rmf_status == "active"
    assert update.step_state == "running"


def test_an_idle_robot_reports_nothing() -> None:
    """`task_id` 가 비면 아무 사실도 없다. 완료인지 취소인지 구분할 수 없다."""
    updates = normalize_fleet_state(
        _fleet(_robot("PK_01", "", RobotMode.MODE_IDLE)), observed_at_ms=1_000
    )

    assert updates == ()


def test_every_mode_that_still_holds_a_task_counts_as_assigned() -> None:
    """작업을 든 채 잠깐 서 있어도 낙찰은 유효하다. 여기서 실패로 만들지 않는다."""
    for mode in (
        RobotMode.MODE_IDLE,
        RobotMode.MODE_MOVING,
        RobotMode.MODE_PAUSED,
        RobotMode.MODE_WAITING,
        RobotMode.MODE_DOCKING,
        RobotMode.MODE_GOING_HOME,
        RobotMode.MODE_CHARGING,
    ):
        updates = normalize_fleet_state(
            _fleet(_robot("PK_01", "task-1", mode)), observed_at_ms=1
        )
        assert len(updates) == 1, f"mode {mode} 에서 낙찰이 사라졌다"
        assert updates[0].step_state == "running"


def test_two_robots_report_independently() -> None:
    updates = normalize_fleet_state(
        _fleet(
            _robot("PK_01", "task-a", RobotMode.MODE_MOVING),
            _robot("PK_02", "", RobotMode.MODE_IDLE),
            _robot("PK_03", "task-c", RobotMode.MODE_WAITING),
        ),
        observed_at_ms=5,
    )

    assert [(u.robot_name, u.task_id) for u in updates] == [
        ("PK_01", "task-a"),
        ("PK_03", "task-c"),
    ]


def test_a_negative_observation_time_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_fleet_state(
            _fleet(_robot("PK_01", "task-1", RobotMode.MODE_MOVING)),
            observed_at_ms=-1,
        )


# --------------------------------------------------------------------------
# observer — 모르는 작업은 무시하고, 아는 작업만 원장에 반영한다
# --------------------------------------------------------------------------

class _Repository:
    def __init__(self, known: set[str]) -> None:
        self._known = known
        self.applied: list = []

    def knows_task(self, task_id: str) -> bool:
        return task_id in self._known

    def apply_task_update(self, update) -> bool:
        self.applied.append(update)
        return True


class _Clock:
    @staticmethod
    def now():
        return type("_T", (), {"nanoseconds": 7_000_000})()


class _Node:
    def __init__(self) -> None:
        self.subscribed: list[tuple] = []
        self.callback = None

    def get_clock(self) -> _Clock:
        return _Clock()

    def create_subscription(self, msg_type, topic, callback, depth):
        self.subscribed.append((msg_type, topic, depth))
        self.callback = callback
        return object()


def _observer_module():
    from control_tower.rmf_adapter import ros_task_client

    return ros_task_client


def test_the_observer_subscribes_to_fleet_states_with_the_fleet_message() -> None:
    """죽은 `task_summaries` 가 아니라 실제로 흐르는 토픽을 봐야 한다."""
    module = _observer_module()
    node = _Node()

    module.RosFleetStateObserver(_Repository(set())).attach(node)

    assert len(node.subscribed) == 1
    msg_type, topic, _ = node.subscribed[0]
    assert topic == "fleet_states"
    assert msg_type is FleetState


def test_only_tasks_the_ledger_knows_are_applied() -> None:
    """RMF 는 우리가 안 낸 작업도 나른다. 모르는 것을 원장에 쓰면 안 된다."""
    module = _observer_module()
    repository = _Repository({"task-ours"})
    node = _Node()
    module.RosFleetStateObserver(repository).attach(node)

    node.callback(
        _fleet(
            _robot("PK_01", "task-ours", RobotMode.MODE_MOVING),
            _robot("PK_02", "task-someone-else", RobotMode.MODE_MOVING),
        )
    )

    assert [u.task_id for u in repository.applied] == ["task-ours"]
    assert repository.applied[0].robot_name == "PK_01"


def test_an_idle_fleet_writes_nothing() -> None:
    module = _observer_module()
    repository = _Repository({"task-ours"})
    node = _Node()
    module.RosFleetStateObserver(repository).attach(node)

    node.callback(_fleet(_robot("PK_01", "", RobotMode.MODE_IDLE)))

    assert repository.applied == []
