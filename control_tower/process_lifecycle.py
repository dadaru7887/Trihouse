"""Let a polling worker finish the cycle it is in before the process exits.

Every worker here claims work, executes it, and reports the result. Those three
are one indivisible unit: a process killed between the claim and the report
leaves the message owned by nobody, and the step behind it stays open until the
claim lease expires. The lease exists precisely because a crash cannot be
prevented — but an operator stopping the stack is not a crash, and should not
cost anyone a lease window.

So a shutdown request is recorded rather than acted on immediately. The poll
loop reads it at the top of each cycle, which means a signal that arrives
mid-cycle lets the claim reach its report before the loop ends.

`SIGTERM` matters as much as `SIGINT` here. The bring-up script tears its
children down with a plain `kill`, and Python's default action for `SIGTERM`
terminates the process outright — no `finally`, no in-flight report.
"""

from __future__ import annotations

import signal
import threading
from types import FrameType


# Signals that mean "stop accepting new work". SIGINT arrives when an operator
# presses Ctrl+C; SIGTERM when the bring-up script or a container runtime stops
# the process.
SHUTDOWN_SIGNALS = (signal.SIGINT, signal.SIGTERM)


class ShutdownSignal:
    """A latch that turns a termination signal into a cycle-boundary exit."""

    def __init__(self) -> None:
        self._requested = threading.Event()

    @classmethod
    def installed(cls) -> "ShutdownSignal":
        """Build one and register it for every shutdown signal."""
        instance = cls()
        instance.install()
        return instance

    def install(self) -> None:
        for number in SHUTDOWN_SIGNALS:
            signal.signal(number, self._on_signal)

    def request(self) -> None:
        self._requested.set()

    @property
    def requested(self) -> bool:
        return self._requested.is_set()

    def keep_running_with(self, is_alive: object) -> object:
        """Combine this latch with the ROS context check the loops already use."""

        def keep_running() -> bool:
            return bool(is_alive()) and not self.requested  # type: ignore[operator]

        return keep_running

    def sleep(self, seconds: float) -> None:
        """Wait between cycles, but wake the moment shutdown is requested.

        `time.sleep` would serve the interval out in full: since PEP 475 it
        resumes after a signal handler runs, so a stop would wait for the whole
        poll interval before taking effect.
        """
        self._requested.wait(seconds)

    def _on_signal(self, number: int, frame: FrameType | None) -> None:
        del number, frame
        self.request()


__all__ = ["SHUTDOWN_SIGNALS", "ShutdownSignal"]
