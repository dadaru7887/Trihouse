"""기존 MySQL 스키마를 사용하는 RMF outbox repository 계약 테스트."""

from dataclasses import dataclass

import pytest

from control_tower.database.repositories.rmf_task_repository import (
    MysqlRmfTaskRepository,
)
from control_tower.rmf_adapter.task_api import DispatchAcceptance, RmfTaskUpdate
from control_tower.rmf_adapter.order_task import RmfAssignmentWindow


@dataclass(frozen=True)
class Executed:
    sql: str
    params: tuple


class RecordingCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = 0
        self._rows = []

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        self.connection.executed.append(Executed(normalized, tuple(params)))
        self._rows = self.connection.select_rows.pop(0) if normalized.startswith("SELECT") else []
        self.rowcount = self.connection.rowcounts.pop(0) if self.connection.rowcounts else 1

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class RecordingConnection:
    def __init__(self, *, select_rows=None, rowcounts=None):
        self.select_rows = list(select_rows or [])
        self.rowcounts = list(rowcounts or [])
        self.executed = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def cursor(self):
        return RecordingCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


def test_claim_uses_skip_locked_and_only_pending_rmf_messages() -> None:
    """동시 worker가 같은 outbox 행을 중복 제출하는 회귀를 막는다."""
    connection = RecordingConnection(
        select_rows=[
            [
                (
                    "req-1",
                    42,
                    "대기1",
                    "pinky_fleet",
                    1_000,
                    0,
                )
            ]
        ]
    )
    repository = MysqlRmfTaskRepository(lambda: connection)

    messages = repository.claim_pending(10)

    select = connection.executed[0]
    update = connection.executed[1]
    assert "direction = 'outbound'" in select.sql
    assert "channel = 'rmf'" in select.sql
    assert "state = 'pending'" in select.sql
    assert "FOR UPDATE SKIP LOCKED" in select.sql
    assert "j.priority_rank" in select.sql
    assert "MIN(il.expires_at)" in select.sql
    assert "JSON_EXTRACT(j.context, '$.urgent')" in select.sql
    assert "j.job_id" in select.sql
    assert select.params == (30, 10)
    assert "SET state = 'sent', attempts = attempts + 1" in update.sql
    assert update.params == ("req-1", 30)
    assert messages[0].message_id == "req-1"
    assert messages[0].attempts == 1
    assert connection.commits == 1


def test_claim_recovers_a_stale_sent_message_with_the_same_request_id() -> None:
    """발행 직후 worker가 죽어 sent 행이 영구 고착되는 회귀를 막는다."""
    connection = RecordingConnection(
        select_rows=[
            [
                (
                    "req-stale",
                    43,
                    "포장대1",
                    "pinky_fleet",
                    2_000,
                    1,
                )
            ]
        ]
    )
    repository = MysqlRmfTaskRepository(
        lambda: connection, sent_timeout_seconds=30
    )

    messages = repository.claim_pending(10)

    select = connection.executed[0]
    update = connection.executed[1]
    assert "im.state = 'sent'" in select.sql
    assert "TIMESTAMPADD(SECOND, -%s, NOW(6))" in select.sql
    assert select.params == (30, 10)
    assert "state = 'sent'" in update.sql
    assert "TIMESTAMPADD(" in update.sql
    assert "SECOND, -%s, NOW(6))" in update.sql
    assert update.params == ("req-stale", 30)
    assert messages[0].message_id == "req-stale"
    assert messages[0].attempts == 2


def test_acknowledge_links_task_and_message_in_one_transaction() -> None:
    """message ack만 되고 job step task ID가 누락되는 부분 저장을 막는다."""
    connection = RecordingConnection(rowcounts=[1, 1])
    repository = MysqlRmfTaskRepository(lambda: connection)

    accepted = repository.acknowledge(
        "req-1",
        42,
        DispatchAcceptance(True, "rmf-task-1", "queued"),
    )

    assert accepted is True
    assert "rmf_task_id = %s" in connection.executed[0].sql
    assert "rmf_task_id IS NULL OR rmf_task_id = %s" in connection.executed[0].sql
    assert connection.executed[0].params == (
        "rmf-task-1",
        "queued",
        42,
        "rmf-task-1",
    )
    assert "state = 'acknowledged'" in connection.executed[1].sql
    assert connection.commits == 1
    assert connection.rollbacks == 0


def test_acknowledge_rolls_back_when_step_has_another_task_id() -> None:
    """기존 RMF task ID를 새 응답으로 덮어쓰는 회귀를 막는다."""
    connection = RecordingConnection(rowcounts=[0])
    repository = MysqlRmfTaskRepository(lambda: connection)

    accepted = repository.acknowledge(
        "req-1",
        42,
        DispatchAcceptance(True, "rmf-task-2", "queued"),
    )

    assert accepted is False
    assert connection.commits == 0
    assert connection.rollbacks == 1


def test_acknowledge_projects_assignment_into_device_time_slot_atomically() -> None:
    """RMF는 낙찰됐지만 DB 업무·Pinky 예약이 분리 저장되는 회귀를 막는다."""
    connection = RecordingConnection(
        select_rows=[[("pinky-01",)], []],
    )
    repository = MysqlRmfTaskRepository(lambda: connection)
    assignment = RmfAssignmentWindow(
        "rmf-task-1", "pinky_fleet", "PK-01", 2_000, 8_000
    )

    accepted = repository.acknowledge(
        "req-1",
        42,
        DispatchAcceptance(
            True, "rmf-task-1", "queued", assignment=assignment
        ),
    )

    assert accepted is True
    assert "FROM devices" in connection.executed[0].sql
    assert "FOR UPDATE" in connection.executed[0].sql
    assert connection.executed[0].params == ("pinky_fleet", "PK-01")
    assert "FROM reservations" in connection.executed[1].sql
    assert "planned_start_at <" in connection.executed[1].sql
    assert connection.executed[1].params == (
        "pinky-01",
        8_000,
        2_000,
    )
    statements = [executed.sql for executed in connection.executed]
    assert any("UPDATE jobs" in sql for sql in statements)
    assert any("INSERT INTO reservations" in sql for sql in statements)
    assert any("INSERT INTO operation_events" in sql for sql in statements)
    job_update = next(sql for sql in statements if "UPDATE jobs" in sql)
    step_update = next(
        sql
        for sql in statements
        if "UPDATE job_steps" in sql and "assigned_device_id" in sql
    )
    # UPDATE ... JOIN의 SET 평가 순서에 기대지 않고 새 projection마다
    # fencing revision을 정확히 한 번 증가시켜야 한다.
    assert "j.revision = j.revision + 1" in job_update
    assert "assignment_revision = assignment_revision + 1" in step_update
    assert "END, WHERE" not in job_update
    assert "state = 'acknowledged'" in statements[-1]
    assert connection.commits == 1
    assert connection.rollbacks == 0


def test_acknowledge_rejects_an_overlapping_assignment() -> None:
    """같은 Pinky의 겹치는 RMF ETA를 자체적으로 이동해 확정하는 회귀를 막는다."""
    connection = RecordingConnection(
        select_rows=[[("pinky-01",)], [(99, 77)]],
    )
    repository = MysqlRmfTaskRepository(lambda: connection)

    accepted = repository.acknowledge(
        "req-2",
        42,
        DispatchAcceptance(
            True,
            "rmf-task-2",
            "queued",
            assignment=RmfAssignmentWindow(
                "rmf-task-2", "pinky_fleet", "PK-01", 4_000, 9_000
            ),
        ),
    )

    assert accepted is False
    assert not any(
        "INSERT INTO reservations" in executed.sql
        for executed in connection.executed
    )
    assert connection.commits == 0
    assert connection.rollbacks == 1


def test_acknowledge_same_booking_and_slot_is_idempotent() -> None:
    """worker 재시도가 같은 time-slot을 실패 또는 중복 INSERT하는 회귀를 막는다."""
    connection = RecordingConnection(
        select_rows=[[("pinky-01",)], [(99, 42, "rmf-task-1")]],
    )
    repository = MysqlRmfTaskRepository(lambda: connection)

    accepted = repository.acknowledge(
        "req-1",
        42,
        DispatchAcceptance(
            True,
            "rmf-task-1",
            "queued",
            assignment=RmfAssignmentWindow(
                "rmf-task-1", "pinky_fleet", "PK-01", 2_000, 8_000
            ),
        ),
    )

    assert accepted is True
    assert not any(
        "INSERT INTO reservations" in executed.sql
        for executed in connection.executed
    )
    assert not any(
        "UPDATE jobs" in executed.sql for executed in connection.executed
    )
    assert "state = 'acknowledged'" in connection.executed[-1].sql
    assert connection.commits == 1


def test_acknowledge_rejects_an_unregistered_rmf_robot() -> None:
    """RMF robot 이름을 임의 device ID로 저장하는 회귀를 막는다."""
    connection = RecordingConnection(select_rows=[[]])
    repository = MysqlRmfTaskRepository(lambda: connection)

    accepted = repository.acknowledge(
        "req-3",
        42,
        DispatchAcceptance(
            True,
            "rmf-task-3",
            "queued",
            assignment=RmfAssignmentWindow(
                "rmf-task-3", "pinky_fleet", "PK-unknown", 4_000, 9_000
            ),
        ),
    )

    assert accepted is False
    assert connection.rollbacks == 1


def test_task_update_is_fenced_by_task_id_and_observed_time() -> None:
    """오래된 RMF summary가 최신 step 상태를 되돌리는 회귀를 막는다."""
    connection = RecordingConnection(rowcounts=[1])
    repository = MysqlRmfTaskRepository(lambda: connection)
    update = RmfTaskUpdate(
        task_id="rmf-task-1",
        rmf_status="active",
        step_state="running",
        fleet_name="pinky_fleet",
        robot_name="PK-01",
        observed_at_ms=2_000,
    )

    applied = repository.apply_task_update(update)

    statement = connection.executed[0]
    assert applied is True
    assert "rmf_task_id = %s" in statement.sql
    assert "rmf_status_observed_at < FROM_UNIXTIME" in statement.sql
    assert "state NOT IN ('succeeded','failed','cancelled')" in statement.sql
    assert statement.params[-2:] == ("rmf-task-1", 2_000)
    assert connection.commits == 1


def test_active_task_marks_matching_reservation_in_use() -> None:
    """Pinky가 출발해도 time-slot이 reserved로 남는 회귀를 막는다."""
    connection = RecordingConnection(rowcounts=[1, 1])
    repository = MysqlRmfTaskRepository(lambda: connection)

    applied = repository.apply_task_update(
        RmfTaskUpdate(
            "rmf-task-1",
            "active",
            "running",
            "pinky_fleet",
            "PK-01",
            2_000,
        )
    )

    assert applied is True
    reservation = connection.executed[1]
    assert "UPDATE reservations r" in reservation.sql
    assert "r.state = %s" in reservation.sql
    assert "entered_at = COALESCE" in reservation.sql
    assert reservation.params == ("in_use", "rmf-task-1")


def test_summary_assignment_creates_reservation_when_submit_response_had_no_eta() -> None:
    """비동기 RMF bidding 뒤 낙찰 Pinky 예약이 영구 누락되는 회귀를 막는다."""
    connection = RecordingConnection(
        select_rows=[[(42,)], [("pinky-01",)], []],
        rowcounts=[1, 1, 1, 1, 1, 1, 1],
    )
    repository = MysqlRmfTaskRepository(lambda: connection)

    applied = repository.apply_task_update(
        RmfTaskUpdate(
            "rmf-task-1",
            "queued",
            "pending",
            "pinky_fleet",
            "PK-01",
            1_000,
            planned_start_ms=2_000,
            planned_end_ms=8_000,
        )
    )

    assert applied is True
    assert any(
        "INSERT INTO reservations" in executed.sql
        for executed in connection.executed
    )
    assert connection.commits == 1


@pytest.mark.parametrize(
    ("rmf_status", "step_state", "reservation_state"),
    [
        ("completed", "succeeded", "released"),
        ("failed", "failed", "cancelled"),
        ("canceled", "cancelled", "cancelled"),
    ],
)
def test_terminal_task_releases_or_cancels_matching_reservation(
    rmf_status: str,
    step_state: str,
    reservation_state: str,
) -> None:
    """RMF terminal task 뒤 활성 예약이 영구 잔존하는 회귀를 막는다."""
    connection = RecordingConnection(rowcounts=[1, 1])
    repository = MysqlRmfTaskRepository(lambda: connection)

    repository.apply_task_update(
        RmfTaskUpdate(
            "rmf-task-1",
            rmf_status,
            step_state,
            "pinky_fleet",
            "PK-01",
            3_000,
        )
    )

    assert "released_at = COALESCE" in connection.executed[1].sql
    assert connection.executed[1].params == (
        reservation_state,
        "rmf-task-1",
    )


def test_unknown_task_is_not_known() -> None:
    """미등록 RMF task update가 임의 업무 단계에 적용되는 회귀를 막는다."""
    connection = RecordingConnection(select_rows=[[]])
    repository = MysqlRmfTaskRepository(lambda: connection)

    assert repository.knows_task("unknown") is False
    assert connection.executed[0].params == ("unknown",)
