"""정차 대기 코루틴이 rclpy executor 에서 **실제로 도는지** 본다. (D18)

## 왜 이 파일이 따로 필요한가

`test_fleet_node_waits_for_stop.py` 는 `fleet_node.py` 의 **소스 문자열**을 본다 —
`may_report_arrival` 이 등장하는지, 호출 순서가 맞는지. 배선이 되었다는 것은
증명하지만 **그 배선이 실행되는지는 증명하지 않는다.**

그 차이가 실제 결함을 숨겼다. `_settle_before_arrival` 이 `asyncio.sleep` 을 await
했는데, rclpy executor 는 asyncio 이벤트 루프를 돌리지 않는다.

```
rclpy/task.py  Task._execute_coroutine_step:
    result = coro.send(None)          ← 직접 밀어 준다
    ...
    elif isinstance(result, Future):  ← Future 면 완료 시 재개
    elif result is None:              ← None 이면 다음 spin 에 재개
    else: raise TypeError             ← 그 밖은 거부
```

`rclpy.task` 에는 `asyncio` import 가 **하나도 없다.** 그리고 `asyncio.sleep(delay)`
는 `delay > 0` 이면 `get_running_loop()` 를 먼저 부르므로 asyncio 루프 없이는
`RuntimeError: no running event loop` 로 죽는다.

**하필 죽는 자리가 결함이 나는 자리와 같다.** 로봇이 이미 정차해 있으면
`may_report_arrival` 이 곧바로 True 를 돌려주고 `sleep` 에 닿지 않아 정상으로 보인다.
감쇠 중일 때만 `sleep` 에 닿고 그때 죽는다 — 즉 **고치려던 그 레이스에서만 터진다.**
원래 버그와 같은 모양이다.

## 이 파일이 하는 일

rclpy executor 가 코루틴을 미는 방식(`send(None)` + yield 계약)을 그대로 재현해
`_settle_before_arrival` 을 **실행한다.** ROS 노드를 띄우지 않는다 — 필요한 것만
가진 대역을 메서드에 묶는다.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "trihouse_pinky_fleet"))

rclpy_task = pytest.importorskip(
    "rclpy.task", reason="rclpy 가 필요하다. 3단 source 뒤에 돌려라"
)
fleet_node = pytest.importorskip("trihouse_pinky_fleet.fleet_node")

Future = rclpy_task.Future


class _Parameter:
    def __init__(self, value: float) -> None:
        self.value = value


class _Now:
    def __init__(self, nanoseconds: int) -> None:
        self.nanoseconds = nanoseconds


class _Clock:
    """호출마다 시간이 흐른다. 실제 executor 처럼 대기가 진행되게 한다."""

    def __init__(self, step_ns: int = 50_000_000) -> None:
        self._ns = 0
        self._step_ns = step_ns

    def now(self) -> _Now:
        current = self._ns
        self._ns += self._step_ns
        return _Now(current)


class _FakeNode:
    """`_settle_before_arrival` 이 실제로 만지는 것만 갖는다."""

    def __init__(
        self,
        *,
        stationary: bool,
        timeout_s: float = 2.0,
        fire_immediately: bool = True,
    ) -> None:
        self.stationary = stationary
        self._timeout_s = timeout_s
        self._clock = _Clock()
        self._fire_immediately = fire_immediately
        self.pending: list = []
        self.created_timers = 0
        self.destroyed_timers = 0

    def get_parameter(self, name: str) -> _Parameter:
        assert name == "arrival_stop_timeout_s"
        return _Parameter(self._timeout_s)

    def get_clock(self) -> _Clock:
        return self._clock

    def create_timer(self, period_s: float, callback) -> object:
        """일회성 timer 를 **즉시** 발화시킨다.

        실제 rclpy 는 `create_timer` 가 돌아온 뒤에 발화하지만, 여기서 일부러
        가장 이른 시점에 부른다. 발화 콜백이 아직 묶이지 않은 이름을 참조하면
        그 자리에서 드러난다 — 실제로 그 결함을 이 대역이 잡았다.
        """
        self.created_timers += 1
        timer = type("_Timer", (), {"cancel": lambda self: None})()
        if self._fire_immediately:
            callback()
        else:
            # 실제 rclpy 처럼 나중에 발화한다. 그래야 Future 가 pending 인 채로
            # await 되어 rclpy 가 보는 yield 값이 실제로 드러난다.
            self.pending.append(callback)
        return timer

    def destroy_timer(self, timer: object) -> None:
        self.destroyed_timers += 1

    def _sleep(self, seconds: float):
        """실제 구현을 그대로 쓴다 — 이것이 rclpy 가 받는 값을 내는지가 검증 대상이다."""
        return fleet_node.FleetNode._sleep(self, seconds)


def _drive(coro, *, max_steps: int = 200) -> None:
    """rclpy `Task._execute_coroutine_step` 과 같은 규칙으로 코루틴을 민다."""
    for _ in range(max_steps):
        try:
            yielded = coro.send(None)
        except StopIteration:
            return
        if isinstance(yielded, Future):
            if not yielded.done():
                yielded.set_result(None)
            continue
        if yielded is None:
            continue
        raise TypeError(
            f"rclpy 는 Future 또는 None 만 받는다. 받은 것: {type(yielded)}"
        )
    raise AssertionError("코루틴이 끝나지 않았다 — 대기에 상한이 없다")


def test_settling_completes_when_the_robot_is_already_stopped() -> None:
    """이미 멈춘 경우. 여기서는 대기 자체가 일어나지 않는다."""
    node = _FakeNode(stationary=True)
    _drive(fleet_node.FleetNode._settle_before_arrival(node))


def test_settling_completes_while_the_robot_is_still_coasting() -> None:
    """감쇠 중인 경우 — 여기가 실제로 도는지가 이 파일의 요점이다.

    `asyncio.sleep` 을 쓰면 `RuntimeError: no running event loop` 로 죽는다.
    """
    node = _FakeNode(stationary=False, timeout_s=0.5)

    _drive(fleet_node.FleetNode._settle_before_arrival(node))

    # 실제로 양보했다는 증거. 한 번도 안 기다렸다면 배선이 무의미하다.
    assert node.created_timers > 0, "정차를 기다리지 않고 곧바로 돌아왔다"


def test_the_wait_yields_only_what_rclpy_accepts() -> None:
    """yield 값이 `Future` 나 `None` 이 아니면 rclpy 가 `TypeError` 로 거부한다.

    timer 를 **지연** 발화시켜 Future 가 pending 인 채로 await 되게 한다. 즉시
    발화하면 Future 가 이미 완료라 `__await__` 이 yield 없이 끝나고, rclpy 가
    실제로 보는 값이 드러나지 않는다.
    """
    node = _FakeNode(stationary=False, timeout_s=0.2, fire_immediately=False)
    coro = fleet_node.FleetNode._settle_before_arrival(node)

    yielded = coro.send(None)

    assert isinstance(yielded, Future) or yielded is None, (
        f"rclpy executor 가 거부하는 값을 yield 한다: {type(yielded)}"
    )
    assert node.pending, "timer 를 만들지 않았다 — 양보하지 않는다는 뜻이다"
    coro.close()


def test_the_timer_is_destroyed_once_the_wait_is_over() -> None:
    """대기마다 timer 를 만들므로 정리하지 않으면 완주 한 번에 수십 개가 쌓인다."""
    node = _FakeNode(stationary=False, timeout_s=0.2)

    _drive(fleet_node.FleetNode._settle_before_arrival(node))

    assert node.created_timers > 0
    assert node.destroyed_timers == node.created_timers, (
        f"만든 timer {node.created_timers} 개 중 {node.destroyed_timers} 개만 정리했다"
    )
