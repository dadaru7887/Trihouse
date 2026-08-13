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
