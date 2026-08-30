"""Crash-safe delivery of recovery facts from the 5080 to the Gateway."""

from .queue import RecoveryMessage, enqueue

__all__ = ["RecoveryMessage", "enqueue"]
