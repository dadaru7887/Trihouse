"""Control Tower RMF task outbox의 멱등 worker와 저장소 계약."""

from dataclasses import dataclass, replace
from typing import Protocol

from .task_api import (
    DispatchAcceptance,
    GoToPlaceRequest,
    RmfTaskUpdate,
    build_dispatch_request,
)


@dataclass(frozen=True)
class RmfOutboxMessage:
    message_id: str
    job_step_id: int
    waypoint: str
    fleet_name: str
    request_time_ms: int
    attempts: int = 0
    state: str = "pending"
    external_reference: str = ""
    last_error: str = ""

    def __post_init__(self) -> None:
        if not self.message_id.strip():
            raise ValueError("message_id is required")
        if self.job_step_id <= 0:
            raise ValueError("job_step_id must be positive")
        if not self.waypoint.strip():
            raise ValueError("waypoint is required")
        if not self.fleet_name.strip():
            raise ValueError("fleet_name is required")
        if self.request_time_ms < 0 or self.attempts < 0:
            raise ValueError("time and attempts cannot be negative")


@dataclass(frozen=True)
class WorkerReport:
    claimed: int = 0
    acknowledged: int = 0
    retried: int = 0
    dead_lettered: int = 0


class TaskApiTransport(Protocol):
    def submit(
        self, request_id: str, payload: dict[str, object], timeout_s: float
    ) -> DispatchAcceptance: ...


class RmfOutboxRepository(Protocol):
    def claim_pending(self, limit: int) -> tuple[RmfOutboxMessage, ...]: ...

    def acknowledge(
        self,
        message_id: str,
        job_step_id: int,
        acceptance: DispatchAcceptance,
    ) -> bool: ...

    def mark_retry(self, message_id: str, reason: str) -> None: ...

    def mark_dead_letter(self, message_id: str, reason: str) -> None: ...

    def apply_task_update(self, update: RmfTaskUpdate) -> bool: ...

    def knows_task(self, task_id: str) -> bool: ...


class RmfTaskOutboxWorker:
    """claim된 RMF message를 같은 request ID로 제출하고 결과를 저장한다."""

    def __init__(
        self,
        repository: RmfOutboxRepository,
        transport: TaskApiTransport,
        *,
        timeout_s: float = 5.0,
        max_attempts: int = 3,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        self._repository = repository
        self._transport = transport
        self._timeout_s = timeout_s
        self._max_attempts = max_attempts

    def run_once(self, limit: int = 10) -> WorkerReport:
        if limit <= 0:
            raise ValueError("limit must be positive")
        messages = self._repository.claim_pending(limit)
        acknowledged = retried = dead_lettered = 0

        for message in messages:
            request = GoToPlaceRequest(
                request_id=message.message_id,
                job_step_id=message.job_step_id,
                waypoint=message.waypoint,
                fleet_name=message.fleet_name,
                request_time_ms=message.request_time_ms,
            )
            try:
                acceptance = self._transport.submit(
                    message.message_id,
                    build_dispatch_request(request),
                    self._timeout_s,
                )
            except TimeoutError:
                if message.attempts >= self._max_attempts:
                    self._repository.mark_dead_letter(
                        message.message_id, "RMF_TASK_API_TIMEOUT"
                    )
                    dead_lettered += 1
                else:
                    self._repository.mark_retry(
                        message.message_id, "RMF_TASK_API_TIMEOUT"
                    )
                    retried += 1
                continue
            except Exception as error:
                reason = f"RMF_TASK_TRANSPORT_ERROR: {error}"
                if message.attempts >= self._max_attempts:
                    self._repository.mark_dead_letter(message.message_id, reason)
                    dead_lettered += 1
                else:
                    self._repository.mark_retry(message.message_id, reason)
                    retried += 1
                continue

            if not acceptance.accepted:
                reason = acceptance.reason_code or "RMF_TASK_REJECTED"
                if acceptance.detail:
                    reason = f"{reason}: {acceptance.detail}"
                self._repository.mark_dead_letter(message.message_id, reason)
                dead_lettered += 1
                continue

            if self._repository.acknowledge(
                message.message_id, message.job_step_id, acceptance
            ):
                acknowledged += 1
            else:
                self._repository.mark_dead_letter(
                    message.message_id, "RMF_TASK_ID_CONFLICT"
                )
                dead_lettered += 1

        return WorkerReport(
            claimed=len(messages),
            acknowledged=acknowledged,
            retried=retried,
            dead_lettered=dead_lettered,
        )


class InMemoryRmfOutboxRepository:
    """outbox 상태 전이를 실제로 수행하는 단위·통합 테스트 저장소."""

    def __init__(self, messages: list[RmfOutboxMessage] | None = None) -> None:
        self.messages = {message.message_id: message for message in messages or []}
        self.task_ids_by_step: dict[int, str] = {}
        self.task_updates: dict[str, RmfTaskUpdate] = {}

    def claim_pending(self, limit: int) -> tuple[RmfOutboxMessage, ...]:
        claimed: list[RmfOutboxMessage] = []
        for message_id, message in self.messages.items():
            if message.state != "pending":
                continue
            sent = replace(
                message,
                state="sent",
                attempts=message.attempts + 1,
                last_error="",
            )
            self.messages[message_id] = sent
            claimed.append(sent)
            if len(claimed) >= limit:
                break
        return tuple(claimed)

    def acknowledge(
        self,
        message_id: str,
        job_step_id: int,
        acceptance: DispatchAcceptance,
    ) -> bool:
        message = self.messages.get(message_id)
        if message is None or message.state not in ("sent", "acknowledged"):
            return False
        existing = self.task_ids_by_step.get(job_step_id)
        if existing not in (None, acceptance.rmf_task_id):
            self.mark_dead_letter(message_id, "RMF_TASK_ID_CONFLICT")
            return False
        self.task_ids_by_step[job_step_id] = acceptance.rmf_task_id
        self.messages[message_id] = replace(
            message,
            state="acknowledged",
            external_reference=acceptance.rmf_task_id,
            last_error="",
        )
        return True

    def mark_retry(self, message_id: str, reason: str) -> None:
        message = self.messages[message_id]
        self.messages[message_id] = replace(
            message, state="pending", last_error=reason
        )

    def mark_dead_letter(self, message_id: str, reason: str) -> None:
        message = self.messages[message_id]
        self.messages[message_id] = replace(
            message, state="dead_letter", last_error=reason
        )

    def knows_task(self, task_id: str) -> bool:
        return task_id in self.task_ids_by_step.values()

    def apply_task_update(self, update: RmfTaskUpdate) -> bool:
        if not self.knows_task(update.task_id):
            return False
        current = self.task_updates.get(update.task_id)
        if current is not None and update.observed_at_ms <= current.observed_at_ms:
            return False
        self.task_updates[update.task_id] = update
        return True
