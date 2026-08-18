"""Runnable RMF worker node lifecycle tests."""

from pathlib import Path

from control_tower.rmf_adapter.rmf_gateway_worker import RmfGatewayWorkerReport
from control_tower.rmf_adapter.rmf_gateway_worker_node import run_poll_loop


class FakeWorker:
    def __init__(self) -> None:
        self.limits = []

    def run_once(self, *, limit):
        self.limits.append(limit)
        return RmfGatewayWorkerReport(claimed=1, accepted=1)


class FakeLogger:
    def __init__(self) -> None:
        self.messages = []

    def info(self, message):
        self.messages.append(message)


class FakeNode:
    def __init__(self) -> None:
        self.logger = FakeLogger()

    def get_logger(self):
        return self.logger


def test_once_mode_runs_one_claim_cycle_without_sleeping() -> None:
    """The manual command must terminate after one observable claim cycle."""
    worker = FakeWorker()
    node = FakeNode()
    sleeps = []

    run_poll_loop(
        worker,
        node,
        limit=4,
        poll_interval_s=0.25,
        once=True,
        keep_running=lambda: True,
        sleep=sleeps.append,
    )

    assert worker.limits == [4]
    assert sleeps == []
    assert node.logger.messages == [
        "RMF dispatch cycle: claimed=1 accepted=1 rejected=0 indeterminate=0"
    ]


def test_continuous_mode_polls_while_ros_context_is_running() -> None:
    """The runnable node must stop with the ROS context and wait between claims."""
    worker = FakeWorker()
    node = FakeNode()
    states = iter((True, True, False))
    sleeps = []

    run_poll_loop(
        worker,
        node,
        limit=2,
        poll_interval_s=0.5,
        once=False,
        keep_running=lambda: next(states),
        sleep=sleeps.append,
    )

    assert worker.limits == [2, 2]
    assert sleeps == [0.5, 0.5]


class FakeErrorLogger(FakeLogger):
    def __init__(self) -> None:
        super().__init__()
        self.errors = []

    def error(self, message):
        self.errors.append(message)


class FakeErrorNode(FakeNode):
    def __init__(self) -> None:
        self.logger = FakeErrorLogger()


class ExplodingWorker:
    """첫 주기에서만 죽는다 — 한 건의 실패가 영구적이지 않다는 뜻이다."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def run_once(self, *, limit):
        self.calls += 1
        if self.calls == 1:
            raise self.error
        return RmfGatewayWorkerReport(claimed=1, accepted=1)


def test_one_bad_cycle_does_not_kill_the_dispatch_loop() -> None:
    """메시지 한 건의 실패로 프로세스가 죽으면 로봇이 조용히 멈춘다.

    2026-08-18 실측: 취소된 step 을 가리키는 outbox 메시지가 남아 worker 가
    acceptance 를 보고하다 Gateway 에서 409 를 받고 죽었다. dispatch 주기가 통째로
    멈춰 아무 job 도 로봇까지 가지 못했고, 그 사실은 로그를 뒤져야 보였다.
    """
    worker = ExplodingWorker(RuntimeError("HTTP Error 409: Conflict"))
    node = FakeErrorNode()
    states = iter((True, True, False))
    sleeps = []

    run_poll_loop(
        worker,
        node,
        limit=2,
        poll_interval_s=0.5,
        once=False,
        keep_running=lambda: next(states),
        sleep=sleeps.append,
    )

    assert worker.calls == 2
    assert node.logger.errors == [
        "RMF dispatch cycle failed: HTTP Error 409: Conflict"
    ]
    assert node.logger.messages == [
        "RMF dispatch cycle: claimed=1 accepted=1 rejected=0 indeterminate=0"
    ]
    assert sleeps == [0.5, 0.5]


def test_a_failing_cycle_in_once_mode_still_returns() -> None:
    worker = ExplodingWorker(RuntimeError("HTTP Error 409: Conflict"))
    node = FakeErrorNode()

    run_poll_loop(
        worker,
        node,
        limit=2,
        poll_interval_s=0.5,
        once=True,
        keep_running=lambda: True,
        sleep=lambda _seconds: None,
    )

    assert worker.calls == 1
    assert node.logger.errors


def test_worker_node_attaches_the_assignment_observer() -> None:
    """배정 관측자가 런타임에 붙어 있어야 한다.

    RMF 는 제출 즉시 booking 만 만들고 배정은 입찰이 끝난 뒤에 정해진다. 그 배정을
    되돌려 줄 관측자가 붙지 않으면 outbox 는 `RMF_ASSIGNMENT_PENDING` 에서 못
    벗어나고 재시도를 소진해 dead_letter 가 된다. 2026-08-18 에 job 4·6·7·8 이
    모두 이 자리에서 죽었다.
    """
    source = (
        Path(__file__).resolve().parents[1]
        / "rmf_adapter"
        / "rmf_gateway_worker_node.py"
    ).read_text(encoding="utf-8")

    assert "RosTaskSummaryObserver" in source, "관측자를 만들지 않는다"
    assert ".attach(" in source, "관측자를 node 에 붙이지 않는다"


def test_worker_node_stamps_start_time_from_the_ros_clock() -> None:
    """워커는 RMF 와 같은 시계를 써야 한다.

    시뮬에서 fleet adapter 는 `use_sim_time` 으로 돌아 기동 후 몇백 초짜리 시계를
    본다. 워커가 원장의 벽시계를 시작 시각으로 보내면 RMF 는 그 작업을 수십 년
    뒤에나 시작할 수 있는 것으로 읽고, 입찰과 배정은 되지만 로봇은 움직이지 않는다.
    2026-08-19 에 job 9 가 이 자리에서 멈췄다.
    """
    source = (
        Path(__file__).resolve().parents[1]
        / "rmf_adapter"
        / "rmf_gateway_worker_node.py"
    ).read_text(encoding="utf-8")

    assert "now_ms=" in source, "워커에 시계를 넘기지 않는다"
    assert "get_clock()" in source, "ROS 시계를 읽지 않는다"


def test_worker_node_can_run_on_simulation_time() -> None:
    """시뮬에서는 워커도 시뮬 시계로 돌아야 한다.

    `--use-sim-time` 이 없으면 `get_clock()` 은 벽시계를 돌려주고, RMF 와 시계가
    갈라져 작업이 시작되지 않는다. 실기에서는 이 플래그를 주지 않아 벽시계가 맞다.
    """
    source = (
        Path(__file__).resolve().parents[1]
        / "rmf_adapter"
        / "rmf_gateway_worker_node.py"
    ).read_text(encoding="utf-8")

    assert "--use-sim-time" in source, "시뮬 시계로 도는 길이 없다"
    assert 'Parameter("use_sim_time"' in source, "노드 파라미터를 세우지 않는다"


def test_simulation_bringup_runs_the_worker_on_simulation_time() -> None:
    """시뮬 bringup 은 워커를 시뮬 시계로 띄워야 한다."""
    script = (
        Path(__file__).resolve().parents[2]
        / "control_tower"
        / "bringup"
        / "p0_simulation_bringup.sh"
    ).read_text(encoding="utf-8")

    # 모듈 이름은 머리말 주석에도 나온다. 실제 실행 줄은 마지막 등장이다.
    worker_block = script.rsplit("rmf_gateway_worker_node", 1)[1].split("\nfi")[0]
    assert "--use-sim-time" in worker_block
