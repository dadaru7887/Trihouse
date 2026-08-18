"""Nav2 도착과 "정차 완료" 는 다른 사건이다 — 그 사이를 기다리는 코드가 없다. (D16)

## 결함

`fleet_node._execute` 는 Nav2 결과가 온 **그 순간에 딱 한 번**
`workflow.nav_result(..., stationary=self.stationary)` 를 부른다
(`fleet_node.py:195`). 그리고 다시 부르는 코드가 없다 — 호출 지점은 152·163·195
셋뿐이고 앞의 둘은 실패 경로다. `fleet_node` 에는 타이머가 없고(`create_timer` 0곳),
odometry 콜백(`fleet_node.py:84`)은 `self.stationary` 만 갱신한다.

그런데 Nav2 `NavigateToPose` 는 goal tolerance 안에 들어오면 SUCCEEDED 를 준다.
속도 0 을 요구하지 않는다. `velocity_smoother` → `collision_monitor` 체인 때문에
`cmd_vel` 은 그 뒤 0.2~0.5 초 더 감쇠하므로 **결과가 도착하는 순간 로봇은 아직
굴러가고 있을 수 있다.**

그러면 `nav_result` 가 `"waiting for stop"` 을 돌려주고 phase 가 `NAVIGATING` 에
남는다(`workflow.py:72-73`). 아무도 다시 묻지 않으므로 그 상태가 영구히 남고, 이후
모든 `ExecuteTransport` 가 `"robot is not idle"` 로 거절된다(`workflow.py:54-55`).
**한 번의 타이밍 레이스가 로봇을 재기동 전까지 못 쓰게 만든다.**

## 결함은 `workflow` 가 아니라 호출자에 있다

처음에는 `workflow` 가 `NAVIGATING` 을 유지하는 것이 결함이라고 보았다. 아니다.
`nav_result` 는 (succeeded, stationary) 의 순수 함수이고 `"waiting for stop"` 은
**"정차한 뒤에 다시 물어라"** 는 정확한 대답이다. 아래 두 테스트가 그것을 고정한다.
`cancel_navigation()` 이 `IDLE` 로 되돌리는 길도 이미 있다. 즉 `workflow.py` 는
고칠 것이 없고, **한 번 묻고 포기하는 `fleet_node` 가 결함이다.**

## 기존 테스트가 놓친 이유

`test_pinky_sr_policies.py:141` 의 `test_arrival_requires_nav2_and_stationary_...`
는 `nav_result` 를 **연달아 두 번** 부른다 — 먼저 `stationary=False`, 다음
`stationary=True`. 그 테스트는 운영 코드가 하지 않는 재폴링을 스스로 해 주고 있었다.
계약은 재폴링을 전제하는데 노드는 재폴링하지 않는다. 그 간극이 이 파일이 막는 것이다.

`D11-b` 에서 "InMemory double 이 실제와 달라 재현되지 않았다" 와 같은 종류다.

## 부하와 무관하다

RTF 0.19 에서든 0.71 에서든 감쇠 시간은 그대로다. 물리 파라미터로는 사라지지 않고
확률만 달라진다.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "trihouse_pinky_fleet"))

from trihouse_pinky_fleet.workflow import (  # noqa: E402
    JobCommand,
    JobPhase,
    TransportWorkflow,
)

MAP_REVISION = "trihouse_test_01:deadbeef"


def _workflow() -> TransportWorkflow:
    return TransportWorkflow(robot_id="PK_01", expected_map_revision=MAP_REVISION)


def _rmf_navigation(command_id: str) -> JobCommand:
    """RMF 가 낙찰한 이동 한 건. `requires_cargo=False` 가 RMF_NAVIGATION 이다."""
    return JobCommand(
        command_id, "job-1", MAP_REVISION, "RMF_NAVIGATION", requires_cargo=False
    )


# --------------------------------------------------------------------------
# 1. 고쳐야 하는 것 — 정차를 기다리는 판단이 아직 없다 (RED)
# --------------------------------------------------------------------------

def test_the_node_has_a_bounded_wait_before_it_reports_arrival() -> None:
    """도착 보고 전에 정차를 기다리되, 무한히 기다리지는 않는 판단이 필요하다.

    `fleet_node` 는 ROS 노드라 단위 테스트로 세울 수 없다. 그래서 그 결정만
    `arrival.py` 의 순수 함수로 떼어 낸다 — `within_tolerance` 가 이미 사는 곳이고
    같은 성격(도착 판정)이다.
    """
    from trihouse_pinky_fleet.arrival import may_report_arrival

    # 이미 멈췄다 → 곧바로 보고한다.
    assert may_report_arrival(stationary=True, waited_s=0.0, timeout_s=2.0) is True

    # 아직 감쇠 중이고 여유가 남았다 → 기다린다. 여기서 물으면 로봇이 굳는다.
    assert may_report_arrival(stationary=False, waited_s=0.3, timeout_s=2.0) is False

    # 끝내 멈추지 않았다 → 영원히 기다리지 않고 보고한다. 그러면 goal 은
    # `ROBOT_NOT_STOPPED` 로 정직하게 실패하고, 노드가 `cancel_navigation()` 으로
    # 로봇을 되돌릴 수 있다.
    assert may_report_arrival(stationary=False, waited_s=2.0, timeout_s=2.0) is True


# --------------------------------------------------------------------------
# 2. 고치지 말아야 하는 것 — `workflow` 의 현재 계약을 고정한다
# --------------------------------------------------------------------------

def test_waiting_for_stop_is_the_correct_answer_not_a_defect() -> None:
    """`nav_result` 는 순수 함수다. 정차 전이면 `NAVIGATING` 을 유지하는 게 맞다."""
    workflow = _workflow()
    workflow.accept(_rmf_navigation("cmd-1"), ready=True, cargo_confirmed=True)

    moving = workflow.nav_result(succeeded=True, stationary=False)
    assert moving.detail == "waiting for stop"
    assert moving.phase is JobPhase.NAVIGATING

    # 같은 호출을 정차 뒤에 다시 하면 정상 종료한다. 즉 계약에는 길이 있다 —
    # 운영 코드가 그 길을 밟지 않을 뿐이다.
    parked = workflow.nav_result(succeeded=True, stationary=True)
    assert parked.phase is JobPhase.IDLE
    assert parked.detail == "RMF navigation destination reached"


def test_a_stuck_navigation_can_always_be_released_without_a_restart() -> None:
    """timeout 경로의 출구가 이미 있다. 새 phase 를 만들 필요가 없다."""
    workflow = _workflow()
    workflow.accept(_rmf_navigation("cmd-1"), ready=True, cargo_confirmed=True)
    workflow.nav_result(succeeded=True, stationary=False)

    released = workflow.cancel_navigation()
    assert released.phase is JobPhase.IDLE

    # 풀린 뒤에는 다음 명령을 받는다.
    assert workflow.accept(
        _rmf_navigation("cmd-2"), ready=True, cargo_confirmed=True
    ).accepted


# --------------------------------------------------------------------------
# 3. 증상 — 재폴링이 없으면 무엇이 되는가
# --------------------------------------------------------------------------

def test_asking_once_and_giving_up_wedges_the_robot() -> None:
    """운영 코드가 지금 하는 그대로를 재현한다. 이 거절이 영구적이 되는 지점이다."""
    workflow = _workflow()
    workflow.accept(_rmf_navigation("cmd-1"), ready=True, cargo_confirmed=True)

    # `fleet_node.py:195` 가 하는 일 — 딱 한 번, 감쇠 중에.
    workflow.nav_result(succeeded=True, stationary=False)

    # 그 뒤 RMF 가 보내는 모든 이동.
    later = workflow.accept(
        _rmf_navigation("cmd-2"), ready=True, cargo_confirmed=True
    )
    assert later.accepted is False
    assert later.detail == "robot is not idle"


# --------------------------------------------------------------------------
# 4. 상한에 닿았을 때도 출구가 있어야 한다 (D16 두 번째 공백)
# --------------------------------------------------------------------------

def test_timing_out_on_the_stop_wait_still_needs_an_explicit_release() -> None:
    """`nav_result` 만으로는 상한 뒤에도 로봇이 갇힌다. 대기는 확률만 낮춘다.

    정차 대기를 넣으면 레이스 확률은 크게 낮아지지만, **끝내 멈추지 않는 경우**
    `nav_result` 는 여전히 `"waiting for stop"` 을 돌려주고 phase 는 `NAVIGATING`
    에 남는다. 그러면 2초 뒤에 똑같이 갇힌다.

    아래가 그 사실이다 — 대기 뒤에도 `cancel_navigation()` 을 부르지 않으면
    로봇은 다음 명령을 받지 못한다.
    """
    workflow = _workflow()
    workflow.accept(_rmf_navigation("cmd-1"), ready=True, cargo_confirmed=True)

    # 상한까지 기다렸는데도 안 멈춘 상태로 보고했다.
    timed_out = workflow.nav_result(succeeded=True, stationary=False)
    assert timed_out.detail == "waiting for stop"

    # 여기서 놓아 주지 않으면 —
    assert not workflow.accept(
        _rmf_navigation("cmd-2"), ready=True, cargo_confirmed=True
    ).accepted

    # 놓아 주면 다음 명령을 받는다. 노드가 이것을 불러야 한다.
    workflow.cancel_navigation()
    assert workflow.accept(
        _rmf_navigation("cmd-3"), ready=True, cargo_confirmed=True
    ).accepted


def test_the_node_releases_the_workflow_when_the_stop_wait_times_out() -> None:
    """`fleet_node` 가 그 해제를 실제로 하는지 본다.

    `_execute` 는 ROS action 콜백 전체라 단위로 실행할 수 없어 배선을 소스로
    확인한다. **이 테스트가 증명하는 것은 호출이 있다는 것뿐이고**, 그것이 옳게
    도는지는 위의 workflow 테스트와 시뮬 실측이 함께 받쳐 준다.

    범위를 좁히는 것이 중요하다. 처음 쓴 판본은 `ROBOT_NOT_STOPPED` 를 문자열로
    찾아 **45줄의 주석**에 걸렸고, 그 뒤에서 `_cancel` 콜백(244줄)의 무관한
    `cancel_navigation` 을 찾아 **수정 없이 통과**했다. 그래서 여기서는 코드에만
    나타나는 표현식으로 시작해 `_execute` 안에서만 본다.
    """
    node_source = (
        Path(__file__).resolve().parents[1]
        / "trihouse_pinky_fleet"
        / "trihouse_pinky_fleet"
        / "fleet_node.py"
    ).read_text(encoding="utf-8")

    # 주석이 아니라 reason_code 식. 그리고 `_execute` 밖은 보지 않는다.
    reason_at = node_source.index("else 'ROBOT_NOT_STOPPED'")
    execute_ends_at = node_source.index("def _cancel")
    timeout_path = node_source[reason_at:execute_ends_at]

    assert "cancel_navigation" in timeout_path, (
        "정차 대기로 실패한 뒤 workflow 를 놓아 주지 않는다 — 상한에 닿으면 "
        "로봇이 그대로 갇힌다. 대기는 확률만 낮춘 것이 된다"
    )
