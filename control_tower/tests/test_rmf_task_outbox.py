"""RMF task outbox의 claim·ack·retry 멱등성 테스트."""

from control_tower.rmf_adapter.task_api import DispatchAcceptance
from control_tower.rmf_adapter.task_outbox import (
    InMemoryRmfOutboxRepository,
    RmfOutboxMessage,
    RmfTaskOutboxWorker,
)


def _pending_message(*, attempts: int = 0) -> RmfOutboxMessage:
    return RmfOutboxMessage(
        message_id="req-1",
        job_step_id=42,
        waypoint="대기1",
        fleet_name="pinky_fleet",
        robot_name="PK_01",
        request_time_ms=1_000,
        attempts=attempts,
    )


class SuccessTransport:
    def submit(self, request_id, payload, timeout_s):
        return DispatchAcceptance(
            True,
            rmf_task_id="rmf-task-1",
            rmf_status="queued",
        )


class TimeoutTransport:
    def submit(self, request_id, payload, timeout_s):
        raise TimeoutError("RMF task API timed out")


class RejectingTransport:
    def submit(self, request_id, payload, timeout_s):
        return DispatchAcceptance(
            False,
            reason_code="RMF_TASK_REJECTED",
            detail="unknown waypoint",
        )


def test_successful_submit_acknowledges_message_and_links_task_once() -> None:
    """재실행이 같은 업무 단계를 RMF에 두 번 제출하는 회귀를 막는다."""
    repository = InMemoryRmfOutboxRepository([_pending_message()])
    worker = RmfTaskOutboxWorker(repository, SuccessTransport())

    first = worker.run_once(limit=10)
    second = worker.run_once(limit=10)

    message = repository.messages["req-1"]
    assert first.claimed == 1
    assert first.acknowledged == 1
    assert second.claimed == 0
    assert message.state == "acknowledged"
    assert message.external_reference == "rmf-task-1"
    assert message.attempts == 1
    assert repository.task_ids_by_step == {42: "rmf-task-1"}


def test_timeout_retries_the_same_business_request() -> None:
    """timeout 재시도가 새 request ID와 두 번째 업무를 만드는 회귀를 막는다."""
    repository = InMemoryRmfOutboxRepository([_pending_message()])
    worker = RmfTaskOutboxWorker(repository, TimeoutTransport(), max_attempts=3)

    report = worker.run_once(limit=10)

    message = repository.messages["req-1"]
    assert report.retried == 1
    assert message.message_id == "req-1"
    assert message.state == "pending"
    assert message.attempts == 1
    assert message.last_error == "RMF_TASK_API_TIMEOUT"
    assert repository.task_ids_by_step == {}


def test_timeout_after_max_attempts_moves_message_to_dead_letter() -> None:
    """영구 timeout이 무제한 즉시 재시도로 RMF를 압박하는 회귀를 막는다."""
    repository = InMemoryRmfOutboxRepository([_pending_message(attempts=2)])
    worker = RmfTaskOutboxWorker(repository, TimeoutTransport(), max_attempts=3)

    report = worker.run_once(limit=10)

    assert report.dead_lettered == 1
    assert repository.messages["req-1"].state == "dead_letter"
    assert repository.messages["req-1"].attempts == 3


def test_explicit_rmf_rejection_is_not_automatically_retried() -> None:
    """잘못된 waypoint 요청이 자동 재시도로 반복 제출되는 회귀를 막는다."""
    repository = InMemoryRmfOutboxRepository([_pending_message()])
    worker = RmfTaskOutboxWorker(repository, RejectingTransport())

    report = worker.run_once(limit=10)

    message = repository.messages["req-1"]
    assert report.dead_lettered == 1
    assert message.state == "dead_letter"
    assert message.last_error == "RMF_TASK_REJECTED: unknown waypoint"
    assert repository.task_ids_by_step == {}


def test_conflicting_task_id_moves_sent_message_to_dead_letter() -> None:
    """step의 기존 task ID와 충돌한 응답이 sent 상태에 영구 고착되는 회귀를 막는다."""
    repository = InMemoryRmfOutboxRepository([_pending_message()])
    repository.task_ids_by_step[42] = "rmf-task-existing"
    worker = RmfTaskOutboxWorker(repository, SuccessTransport())

    report = worker.run_once(limit=10)

    assert report.acknowledged == 0
    assert report.dead_lettered == 1
    assert repository.messages["req-1"].state == "dead_letter"
    assert repository.messages["req-1"].last_error == "RMF_TASK_ID_CONFLICT"
