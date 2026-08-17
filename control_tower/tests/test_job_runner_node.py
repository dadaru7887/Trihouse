"""Runnable job runner node lifecycle tests."""

from control_tower.task_manager.job_runner import JobRunnerReport
from control_tower.task_manager.job_runner_node import run_poll_loop


class FakeRunner:
    def __init__(self, report=None) -> None:
        self.limits = []
        self._report = report or JobRunnerReport(assigned=(7,), dispatched=(7,))

    def run_once(self, *, limit):
        self.limits.append(limit)
        return self._report


class FakeLogger:
    def __init__(self) -> None:
        self.info_messages = []
        self.warnings = []
        self.errors = []

    def info(self, message):
        self.info_messages.append(message)

    def warning(self, message):
        self.warnings.append(message)

    def error(self, message):
        self.errors.append(message)


class FakeNode:
    def __init__(self) -> None:
        self.logger = FakeLogger()

    def get_logger(self):
        return self.logger


def test_once_mode_runs_one_cycle_without_sleeping() -> None:
    """The manual command must terminate after one observable cycle."""
    runner = FakeRunner()
    node = FakeNode()
    sleeps = []

    run_poll_loop(
        runner,
        node,
        limit=4,
        poll_interval_s=0.25,
        once=True,
        keep_running=lambda: True,
        sleep=sleeps.append,
    )

    assert runner.limits == [4]
    assert sleeps == []
    assert node.logger.info_messages == [
        "job runner cycle: assigned=[7] dispatched=[7] expired=[]"
    ]


def test_continuous_mode_polls_while_the_ros_context_is_running() -> None:
    """The node must stop with the ROS context and wait between cycles."""
    runner = FakeRunner()
    node = FakeNode()
    states = iter((True, True, False))
    sleeps = []

    run_poll_loop(
        runner,
        node,
        limit=2,
        poll_interval_s=0.5,
        once=False,
        keep_running=lambda: next(states),
        sleep=sleeps.append,
    )

    assert runner.limits == [2, 2]
    assert sleeps == [0.5, 0.5]


def test_an_idle_cycle_stays_quiet() -> None:
    """A one-second poll must not fill the log when there is nothing to do."""
    runner = FakeRunner(JobRunnerReport())
    node = FakeNode()

    run_poll_loop(
        runner,
        node,
        limit=1,
        poll_interval_s=1.0,
        once=True,
        keep_running=lambda: True,
        sleep=lambda _: None,
    )

    assert node.logger.info_messages == []


def test_blocked_and_failed_jobs_are_surfaced_at_their_own_severity() -> None:
    """A stuck job must be visible without being mistaken for a crash."""
    runner = FakeRunner(
        JobRunnerReport(blocked=("job 3: no free robot",), errors=("job 4: 409",))
    )
    node = FakeNode()

    run_poll_loop(
        runner,
        node,
        limit=1,
        poll_interval_s=1.0,
        once=True,
        keep_running=lambda: True,
        sleep=lambda _: None,
    )

    assert node.logger.warnings == ["job runner blocked: job 3: no free robot"]
    assert node.logger.errors == ["job runner error: job 4: 409"]
