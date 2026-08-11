"""작업 전이와 비상 승인 이력을 남기는 SQLite 저장소.

운영 DB adapter로 바꿔도 request ID 멱등성과 승인 주체/시각 필드는 유지한다.
"""

from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True)
class AuditEvent:
    job_id: str
    kind: str
    occurred_at_s: float
    operator_id: str = ''


@dataclass(frozen=True)
class IncidentRecord:
    incident_id: str
    camera_id: str
    location_id: str
    state: str
    occurred_at_s: float
    approved_by: str = ''
    approved_at_s: float | None = None


class AuditRepository:
    def __init__(self, database_path: str) -> None:
        self._connection = sqlite3.connect(database_path)
        self._connection.execute('PRAGMA foreign_keys = ON')
        self._connection.executescript('''
            CREATE TABLE IF NOT EXISTS task_audit_events (
              id INTEGER PRIMARY KEY,
              job_id TEXT NOT NULL,
              event_kind TEXT NOT NULL,
              occurred_at_s REAL NOT NULL,
              operator_id TEXT NOT NULL DEFAULT '',
              request_id TEXT UNIQUE
            );
            CREATE TABLE IF NOT EXISTS incidents (
              incident_id TEXT PRIMARY KEY,
              camera_id TEXT NOT NULL,
              location_id TEXT NOT NULL,
              state TEXT NOT NULL,
              occurred_at_s REAL NOT NULL,
              approved_by TEXT NOT NULL DEFAULT '',
              approved_at_s REAL
            );
        ''')

    def close(self) -> None:
        self._connection.close()

    def record_stage(self, job_id: str, order_id: str, robot_id: str, step: str, result: str, *, occurred_at_s: float) -> None:
        if not all((job_id, order_id, robot_id, step, result)):
            raise ValueError('job, order, robot, step, and result are required')
        self._connection.execute(
            'INSERT INTO task_audit_events (job_id, event_kind, occurred_at_s) VALUES (?, ?, ?)',
            (job_id, f'{step}:{result}', occurred_at_s),
        )
        self._connection.commit()

    def record_intervention(self, job_id: str, *, request_id: str, operator_id: str, action: str, reason: str, occurred_at_s: float) -> bool:
        if not all((job_id, request_id, operator_id, action, reason)):
            raise ValueError('intervention fields are required')
        try:
            self._connection.execute(
                'INSERT INTO task_audit_events (job_id, event_kind, occurred_at_s, operator_id, request_id) VALUES (?, ?, ?, ?, ?)',
                (job_id, f'INTERVENTION:{action}', occurred_at_s, operator_id, request_id),
            )
        except sqlite3.IntegrityError:
            return False
        self._connection.commit()
        return True

    def job_history(self, job_id: str) -> tuple[AuditEvent, ...]:
        rows = self._connection.execute(
            'SELECT job_id, event_kind, occurred_at_s, operator_id FROM task_audit_events WHERE job_id = ? ORDER BY id',
            (job_id,),
        ).fetchall()
        return tuple(AuditEvent(*row) for row in rows)

    def open_incident(self, incident_id: str, *, camera_id: str, location_id: str, occurred_at_s: float) -> None:
        if not all((incident_id, camera_id, location_id)):
            raise ValueError('incident, camera, and location are required')
        self._connection.execute(
            'INSERT INTO incidents (incident_id, camera_id, location_id, state, occurred_at_s) VALUES (?, ?, ?, ?, ?)',
            (incident_id, camera_id, location_id, 'OPEN', occurred_at_s),
        )
        self._connection.commit()

    def release_incident(self, incident_id: str, *, operator_id: str, approved_at_s: float) -> None:
        if not operator_id:
            raise ValueError('operator approval is required')
        result = self._connection.execute(
            "UPDATE incidents SET state = 'RELEASED', approved_by = ?, approved_at_s = ? WHERE incident_id = ? AND state = 'OPEN'",
            (operator_id, approved_at_s, incident_id),
        )
        if result.rowcount != 1:
            raise ValueError('incident is missing or not open')
        self._connection.commit()

    def incident(self, incident_id: str) -> IncidentRecord:
        row = self._connection.execute(
            'SELECT incident_id, camera_id, location_id, state, occurred_at_s, approved_by, approved_at_s FROM incidents WHERE incident_id = ?',
            (incident_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f'unknown incident {incident_id}')
        return IncidentRecord(*row)
