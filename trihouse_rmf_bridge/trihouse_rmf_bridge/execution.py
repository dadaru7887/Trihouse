"""RMF activity와 Pinky action 결과를 정확히 한 번 연결하는 lifecycle."""

from dataclasses import dataclass
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class StartDecision:
    accepted: bool
    replaced_command_id: str = ""


@dataclass(frozen=True)
class StopDecision:
    should_cancel_pinky: bool
    command_id: str = ""


@dataclass(frozen=True)
class FinishDecision:
    should_finish_rmf: bool


def _same_activity(current: Any, requested: Any) -> bool:
    if current is requested:
        return True
    compare = getattr(current, "is_same", None)
    return bool(compare(requested)) if callable(compare) else False


class ExecutionRegistry:
    """한 Pinky에 현재 RMF execution 하나만 유지한다."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._activity: Any | None = None
        self._command_id = ""

    def start(self, activity: Any, command_id: str) -> StartDecision:
        if activity is None or not command_id:
            return StartDecision(False)
        with self._lock:
            replaced = self._command_id
            self._activity = activity
            self._command_id = command_id
            return StartDecision(True, replaced)

    def stop(self, activity: Any) -> StopDecision:
        with self._lock:
            if self._activity is None or not _same_activity(self._activity, activity):
                return StopDecision(False)
            command_id = self._command_id
            self._activity = None
            self._command_id = ""
            return StopDecision(True, command_id)

    def finish(self, command_id: str) -> FinishDecision:
        with self._lock:
            if self._activity is None or command_id != self._command_id:
                return FinishDecision(False)
            self._activity = None
            self._command_id = ""
            return FinishDecision(True)

    def current_activity(self) -> Any | None:
        with self._lock:
            return self._activity

    def current_command_id(self) -> str:
        with self._lock:
            return self._command_id
