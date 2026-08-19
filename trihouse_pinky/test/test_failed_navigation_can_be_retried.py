"""실패한 이동은 같은 명령으로 다시 시도할 수 있어야 한다.

## 결함

`TransportWorkflow.accept()` 는 `command_id` 가 같으면 무조건 "duplicate command"
로 답한다(`workflow.py:48-49`). 중복 실행을 막는 장치이고 그 자체는 옳다.

문제는 `nav_result` 의 **실패 경로가 `command_id` 를 지우지 않는다**는 것이다.

```python
# workflow.py:69-71 — 실패
if not succeeded:
    self.phase = JobPhase.IDLE          # phase 만 되돌린다
    return WorkflowResult(False, False, self.phase, "navigation failed")

# 성공 경로들은 함께 지운다
self.command_id = ""
self.job_id = ""
self.phase = JobPhase.IDLE
```

그래서 이동이 한 번 실패하면 그 명령은 **영원히 중복으로 읽힌다.**

```
1. accept(cmd-1)              → phase NAVIGATING
2. nav_result(succeeded=False) → phase IDLE, command_id 는 'cmd-1' 로 남는다
3. RMF 가 같은 작업을 다시 보낸다
4. accept(cmd-1)              → "duplicate command", phase 는 IDLE 그대로
5. `_execute` 는 계속 진행해 Nav2 goal 을 보내고 결과를 받는다
6. nav_result                 → phase 가 NAVIGATING 이 아니라 "no active navigation"
7. 3 으로 돌아간다 — 끝나지 않는다
```

2026-08-19 09:46 실측이 정확히 이 모양이었다.

```
[PK_01] RMF compose.dispatch-14d26888f3 -> (0.841, -0.111, -1.089)
[PK_01] navigation failed
[PK_01] RMF compose.dispatch-14d26888f3 -> (0.841, -0.111, -1.089)
[PK_01] no active navigation          ← 이후 무한 반복
```

step 20 은 `pending` 인 채 멈추고 job 은 전진하지 못한다. **재시도 자체가 불가능해
지므로 부하나 타이밍으로는 풀리지 않는다.**

## 고치는 방향

실패도 종료다. 성공 경로와 같이 `command_id` 를 놓아 준다. 그러면 같은 명령의
재시도가 새 명령으로 받아들여져 `NAVIGATING` 으로 다시 들어간다.

**진짜 중복은 계속 막아야 한다** — 이동이 아직 진행 중일 때 같은 명령이 또 오면
그건 여전히 중복이다. 아래 두 번째 테스트가 그것을 고정한다.
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


def _command(command_id: str) -> JobCommand:
    return JobCommand(
        command_id, "job-1", MAP_REVISION, "RMF_NAVIGATION", requires_cargo=False
    )


def test_the_same_command_can_be_retried_after_a_failed_navigation() -> None:
    """실패는 종료다. 같은 명령이 다시 오면 새로 시작해야 한다."""
    workflow = _workflow()
    workflow.accept(_command("cmd-1"), ready=True, cargo_confirmed=True)

    failed = workflow.nav_result(succeeded=False, stationary=True)
    assert failed.phase is JobPhase.IDLE

    retry = workflow.accept(_command("cmd-1"), ready=True, cargo_confirmed=True)

    assert retry.accepted is True
    assert retry.duplicate is False, (
        "실패한 명령의 재시도를 중복으로 읽으면 phase 가 IDLE 에 남아, 이어지는 "
        "nav_result 가 'no active navigation' 을 돌려주며 무한히 반복된다"
    )
    assert retry.phase is JobPhase.NAVIGATING


def test_a_command_still_in_flight_is_still_a_duplicate() -> None:
    """중복 방어를 없애는 것이 아니다. 진행 중이면 여전히 중복이다."""
    workflow = _workflow()
    workflow.accept(_command("cmd-1"), ready=True, cargo_confirmed=True)

    again = workflow.accept(_command("cmd-1"), ready=True, cargo_confirmed=True)

    assert again.duplicate is True
    assert again.phase is JobPhase.NAVIGATING


def test_a_retry_after_failure_reaches_a_normal_arrival() -> None:
    """재시도가 끝까지 간다. 되살아난 뒤 정상 도착이 되는지 확인한다."""
    workflow = _workflow()
    workflow.accept(_command("cmd-1"), ready=True, cargo_confirmed=True)
    workflow.nav_result(succeeded=False, stationary=True)

    workflow.accept(_command("cmd-1"), ready=True, cargo_confirmed=True)
    arrived = workflow.nav_result(succeeded=True, stationary=True)

    assert arrived.accepted is True
    assert arrived.phase is JobPhase.IDLE
    assert arrived.detail == "RMF navigation destination reached"
