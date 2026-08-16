"""작업 실행 이력과 멱등 명령을 저장하는 repository 계약."""

from dataclasses import dataclass
from typing import Protocol

from .execution_result import CompletionEvent, ExecutionFact, ExecutionOutcome
from .zone_handover import ZoneHandoverSnapshot


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

    def has_execution(self, event_id: str) -> bool:
        """이미 terminal 실행 사실을 저장한 event인지 반환한다."""

    def command_by_uuid(self, command_uuid: str) -> TaskCommand | None:
        """발행한 명령을 UUID로 조회한다."""

    def is_command_active(self, command_uuid: str) -> bool:
        """명령이 아직 결과 대기 또는 전송 대상인지 반환한다."""

    def complete_command(self, command_uuid: str) -> None:
        """terminal 결과를 수락한 명령을 비활성화한다."""

    def invalidate_commands(
        self,
        job_id: str,
        *,
        assignment_revision: int | None = None,
    ) -> int:
        """취소·재배정으로 더 이상 실행하면 안 되는 명령을 무효화한다."""

    def save_handover(self, snapshot: ZoneHandoverSnapshot) -> None: ...

    def load_handover(self, job_id: str) -> ZoneHandoverSnapshot | None: ...

    def clear_handover(self, job_id: str) -> None: ...


class InMemoryExecutionStore:
    """단위·통합 테스트에서 실제 중복 방지 동작을 검증하는 저장소."""

    def __init__(self) -> None:
        self.executions: list[StoredExecution] = []
        self.commands: list[TaskCommand] = []
        self._event_ids: set[str] = set()
        self._terminal_command_uuids: set[str] = set()
        self._command_keys: set[str] = set()
        self._commands_by_uuid: dict[str, TaskCommand] = {}
        self._active_command_uuids: set[str] = set()
        self._handovers: dict[str, ZoneHandoverSnapshot] = {}

    def record_execution(
        self,
        event: CompletionEvent,
        fact: ExecutionFact,
        outcome: ExecutionOutcome,
    ) -> bool:
        if (
            event.event_id in self._event_ids
            or fact.command_uuid in self._terminal_command_uuids
        ):
            return False
        self._event_ids.add(event.event_id)
        self._terminal_command_uuids.add(fact.command_uuid)
        self.executions.append(StoredExecution(event, fact, outcome))
        return True

    def save_command(self, command: TaskCommand) -> bool:
        if command.idempotency_key in self._command_keys:
            return False
        self._command_keys.add(command.idempotency_key)
        self.commands.append(command)
        self._commands_by_uuid[command.command_uuid] = command
        self._active_command_uuids.add(command.command_uuid)
        return True

    def has_execution(self, event_id: str) -> bool:
        return event_id in self._event_ids

    def command_by_uuid(self, command_uuid: str) -> TaskCommand | None:
        return self._commands_by_uuid.get(command_uuid)

    def is_command_active(self, command_uuid: str) -> bool:
        return command_uuid in self._active_command_uuids

    def complete_command(self, command_uuid: str) -> None:
        self._active_command_uuids.discard(command_uuid)

    def invalidate_commands(
        self,
        job_id: str,
        *,
        assignment_revision: int | None = None,
    ) -> int:
        targets = {
            command_uuid
            for command_uuid in self._active_command_uuids
            if (command := self._commands_by_uuid[command_uuid]).job_id == job_id
            and (
                assignment_revision is None
                or command.assignment_revision == assignment_revision
            )
        }
        self._active_command_uuids.difference_update(targets)
        return len(targets)

    def save_handover(self, snapshot: ZoneHandoverSnapshot) -> None:
        self._handovers[snapshot.job_id] = snapshot

    def load_handover(self, job_id: str) -> ZoneHandoverSnapshot | None:
        return self._handovers.get(job_id)

    def clear_handover(self, job_id: str) -> None:
        self._handovers.pop(job_id, None)
