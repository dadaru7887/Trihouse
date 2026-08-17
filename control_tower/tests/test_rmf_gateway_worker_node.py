"""Runnable RMF worker node lifecycle tests."""

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
