"""Shutdown must land on a cycle boundary, never in the middle of a claim."""

import signal

from control_tower.process_lifecycle import SHUTDOWN_SIGNALS, ShutdownSignal


def test_a_fresh_latch_is_not_requested() -> None:
    assert ShutdownSignal().requested is False


def test_requesting_shutdown_stops_the_loop_condition() -> None:
    shutdown = ShutdownSignal()
    keep_running = shutdown.keep_running_with(lambda: True)
    assert keep_running() is True

    shutdown.request()

    assert keep_running() is False


def test_a_dead_ros_context_stops_the_loop_even_without_a_signal() -> None:
    """The existing liveness check must keep working alongside the latch."""
    shutdown = ShutdownSignal()

    assert shutdown.keep_running_with(lambda: False)() is False


def test_sleep_returns_immediately_once_shutdown_is_requested() -> None:
    """`time.sleep` would serve the full interval out; a stop must not wait."""
    shutdown = ShutdownSignal()
    shutdown.request()

    # A real delay here would hang the suite for the full interval.
    shutdown.sleep(30)


def test_both_termination_signals_are_covered() -> None:
    """SIGTERM matters as much as SIGINT: the bring-up script uses a plain kill,
    and Python's default action for it skips every cleanup path."""
    assert set(SHUTDOWN_SIGNALS) == {signal.SIGINT, signal.SIGTERM}


def test_an_installed_latch_catches_a_real_signal() -> None:
    shutdown = ShutdownSignal.installed()
    original = {number: signal.getsignal(number) for number in SHUTDOWN_SIGNALS}
    try:
        signal.raise_signal(signal.SIGTERM)

        assert shutdown.requested is True
    finally:
        for number, handler in original.items():
            signal.signal(number, handler)


def test_a_signal_mid_cycle_still_finishes_that_cycle() -> None:
    """The claim/execute/report unit must not be cut in half by a stop."""
    from control_tower.task_manager.job_runner_node import run_poll_loop
    from control_tower.task_manager.job_runner import JobRunnerReport

    shutdown = ShutdownSignal()
    finished = []

    class SignallingRunner:
        def run_once(self, *, limit):
            # The signal lands while this cycle is still running.
            shutdown.request()
            finished.append(limit)
            return JobRunnerReport()

    class FakeLogger:
        def info(self, message): ...
        def warning(self, message): ...
        def error(self, message): ...

    class FakeNode:
        def get_logger(self):
            return FakeLogger()

    run_poll_loop(
        SignallingRunner(),
        FakeNode(),
        limit=3,
        poll_interval_s=30,
        once=False,
        keep_running=shutdown.keep_running_with(lambda: True),
        sleep=shutdown.sleep,
    )

    # The interrupted cycle ran to completion, and no further cycle started.
    assert finished == [3]
