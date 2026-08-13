"""SQLite-backed immutable TaskEvent outbox."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from uuid import uuid4


_TERMINAL_STATE_BY_EVENT = {
    "started": 1,
    "arrived": 2,
    "canceled": 3,
    "failed": 4,
}


class EventOutbox:
    def __init__(self, path: str | Path, *, max_pending: int = 1000) -> None:
        self.path = Path(path).expanduser()
        self.max_pending = max_pending
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_events (
                  event_id TEXT PRIMARY KEY,
                  payload TEXT NOT NULL,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  retry_count INTEGER NOT NULL DEFAULT 0,
                  last_attempt_at TEXT NULL,
                  status_payload TEXT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rejected_events (
                  event_id TEXT PRIMARY KEY,
                  payload TEXT NOT NULL,
                  reason_code TEXT NOT NULL,
                  rejected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                row[1] for row in connection.execute(
                    "PRAGMA table_info(pending_events)"
                ).fetchall()
            }
            if "status_payload" not in columns:
                connection.execute(
                    "ALTER TABLE pending_events ADD COLUMN status_payload TEXT NULL"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS gateway_state (
                  state_key TEXT PRIMARY KEY,
                  state_value TEXT NOT NULL
                )
                """
            )
            row = connection.execute(
                "SELECT state_value FROM gateway_state WHERE state_key = 'session_id'"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO gateway_state(state_key, state_value) VALUES ('session_id', ?)",
                    (str(uuid4()),),
                )

    @property
    def session_id(self) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_value FROM gateway_state WHERE state_key = 'session_id'"
            ).fetchone()
        assert row is not None
        return str(row[0])

    def next_status_sequence(self) -> int:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state_value FROM gateway_state WHERE state_key = 'status_sequence'"
            ).fetchone()
            sequence = int(row[0]) + 1 if row is not None else 1
            connection.execute(
                """
                INSERT INTO gateway_state(state_key, state_value)
                VALUES ('status_sequence', ?)
                ON CONFLICT(state_key) DO UPDATE SET state_value = excluded.state_value
                """,
                (str(sequence),),
            )
        return sequence

    @property
    def is_full(self) -> bool:
        with self._connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM pending_events"
            ).fetchone()[0]
        return int(count) >= self.max_pending

    def enqueue(
        self,
        payload: dict[str, object],
        *,
        status_payload: dict[str, object] | None = None,
    ) -> None:
        event_id = str(payload.get("event_id", "")).strip()
        if not event_id:
            raise ValueError("event_id is required")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT payload FROM pending_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if existing is not None and existing[0] != encoded:
                raise ValueError("event_id payload is immutable")
            compatible_status = self._compatible_status(payload, status_payload)
            connection.execute(
                """
                INSERT OR IGNORE INTO pending_events(event_id, payload, status_payload)
                VALUES (?, ?, ?)
                """,
                (
                    event_id,
                    encoded,
                    json.dumps(compatible_status, separators=(",", ":"))
                    if compatible_status is not None else None,
                ),
            )

    def pending(self, limit: int = 32) -> tuple[dict[str, object], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM pending_events ORDER BY created_at, event_id LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(json.loads(row[0]) for row in rows)

    def pending_records(
        self, limit: int = 32,
    ) -> tuple[tuple[dict[str, object], dict[str, object] | None], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload, status_payload
                FROM pending_events
                ORDER BY created_at, event_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(
            (json.loads(payload), json.loads(status) if status else None)
            for payload, status in rows
        )

    def attach_status_evidence(self, status_payload: dict[str, object]) -> None:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_id, payload FROM pending_events"
            ).fetchall()
            for event_id, encoded in rows:
                event_payload = json.loads(encoded)
                if self._compatible_status(event_payload, status_payload) is None:
                    continue
                connection.execute(
                    "UPDATE pending_events SET status_payload = ? WHERE event_id = ?",
                    (json.dumps(status_payload, separators=(",", ":")), event_id),
                )

    def mark_attempted(self, event_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE pending_events
                SET retry_count = retry_count + 1, last_attempt_at = CURRENT_TIMESTAMP
                WHERE event_id = ?
                """,
                (event_id,),
            )

    def acknowledge(self, event_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM pending_events WHERE event_id = ?", (event_id,))

    def reject(self, event_id: str, reason_code: str) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM pending_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if row is None:
                return
            connection.execute(
                """
                INSERT OR REPLACE INTO rejected_events(event_id, payload, reason_code)
                VALUES (?, ?, ?)
                """,
                (event_id, row[0], reason_code),
            )
            connection.execute("DELETE FROM pending_events WHERE event_id = ?", (event_id,))

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5.0)

    @staticmethod
    def _compatible_status(
        event_payload: dict[str, object],
        status_payload: dict[str, object] | None,
    ) -> dict[str, object] | None:
        if status_payload is None:
            return None
        expected = _TERMINAL_STATE_BY_EVENT.get(str(event_payload.get("event_type")))
        if expected is None or status_payload.get("navigation_state") != expected:
            return None
        if status_payload.get("task_context") != event_payload.get("task_context"):
            return None
        if status_payload.get("session_id") != event_payload.get("session_id"):
            return None
        return status_payload
