"""작업 실행 이력과 멱등 명령을 저장하는 repository 계약."""

from dataclasses import dataclass
from typing import Protocol

from .execution_result import CompletionEvent, ExecutionFact, ExecutionOutcome


@dataclass(frozen=True)
class TaskCommand:
    """외부 adapter가 at-least-once로 전송할 Control Tower 명령."""

    command_uuid: str
    idempotency_key: str
    job_id: str
    job_step_id: str
    assignment_revision: int
    actor_role: str
    actor_id: str
    command_kind: str
    method_code: str


@dataclass(frozen=True)
class StoredExecution:
    """원본 사실과 결정적으로 분류한 결과의 한 쌍."""

    event: CompletionEvent
    fact: ExecutionFact
    outcome: ExecutionOutcome


class ExecutionStore(Protocol):
    """DB adapter와 메모리 테스트 저장소가 지켜야 하는 최소 계약."""

    def record_execution(
        self,
        event: CompletionEvent,
        fact: ExecutionFact,
        outcome: ExecutionOutcome,
    ) -> bool:
        """새 event면 저장하고 True, 이미 저장된 event면 False를 반환한다."""

    def save_command(self, command: TaskCommand) -> bool:
        """새 idempotency key면 저장하고 True, 기존 명령이면 False를 반환한다."""


class InMemoryExecutionStore:
    """단위·통합 테스트에서 실제 중복 방지 동작을 검증하는 저장소."""

    def __init__(self) -> None:
        self.executions: list[StoredExecution] = []
        self.commands: list[TaskCommand] = []
        self._event_ids: set[str] = set()
        self._command_keys: set[str] = set()

    def record_execution(
        self,
        event: CompletionEvent,
        fact: ExecutionFact,
        outcome: ExecutionOutcome,
    ) -> bool:
        if event.event_id in self._event_ids:
            return False
        self._event_ids.add(event.event_id)
        self.executions.append(StoredExecution(event, fact, outcome))
        return True

    def save_command(self, command: TaskCommand) -> bool:
        if command.idempotency_key in self._command_keys:
            return False
        self._command_keys.add(command.idempotency_key)
        self.commands.append(command)
        return True
