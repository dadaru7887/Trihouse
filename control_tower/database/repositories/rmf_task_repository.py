"""기존 MySQL outbox/job_steps를 사용하는 Open-RMF task repository."""

from collections.abc import Callable
from typing import Any

from control_tower.rmf_adapter.task_api import DispatchAcceptance, RmfTaskUpdate
from control_tower.rmf_adapter.order_task import RmfAssignmentWindow
from control_tower.rmf_adapter.task_outbox import RmfOutboxMessage


class MysqlRmfTaskRepository:
    """PEP 249 connection factory로 RMF message와 read model을 원자 갱신한다."""

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        sent_timeout_seconds: int = 30,
    ) -> None:
        if sent_timeout_seconds <= 0:
            raise ValueError("sent_timeout_seconds must be positive")
        self._connection_factory = connection_factory
        self._sent_timeout_seconds = sent_timeout_seconds

    def claim_pending(self, limit: int) -> tuple[RmfOutboxMessage, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        connection = self._connection_factory()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT im.message_id,
                       im.job_step_id,
                       l.rmf_waypoint_name,
                       JSON_UNQUOTE(JSON_EXTRACT(
                         im.payload, '$.fleet_name')) AS fleet_name,
                       CAST(UNIX_TIMESTAMP(im.created_at) * 1000 AS UNSIGNED),
                       im.attempts,
                       COALESCE(js.assigned_device_id, j.assigned_mobile_id)
                         AS robot_name
                FROM integration_messages im
                JOIN job_steps js ON js.job_step_id = im.job_step_id
                JOIN jobs j ON j.job_id = js.job_id
                JOIN locations l ON l.location_id = js.target_location_id
                WHERE im.direction = 'outbound'
                  AND im.channel = 'rmf'
                  AND im.message_type = 'submit_task'
                  AND (
                    (im.state = 'pending'
                     AND (im.next_attempt_at IS NULL
                          OR im.next_attempt_at <= NOW(6)))
                    OR
                    (im.state = 'sent'
                     AND im.sent_at <= TIMESTAMPADD(SECOND, -%s, NOW(6)))
                  )
                  AND l.state = 'available'
                  AND l.rmf_waypoint_name IS NOT NULL
                  AND JSON_UNQUOTE(JSON_EXTRACT(
                    im.payload, '$.fleet_name')) IS NOT NULL
                  -- Control Tower가 Pinky를 확정하기 전에는 RMF로 보내지 않는다.
                  AND COALESCE(js.assigned_device_id, j.assigned_mobile_id)
                    IS NOT NULL
                  AND (
                    (j.priority = 'critical'
                     AND JSON_EXTRACT(j.context, '$.urgent') = TRUE)
                    OR
                    (j.priority <> 'critical'
                     AND COALESCE(
                       JSON_EXTRACT(j.context, '$.urgent'), FALSE) = FALSE)
                  )
                ORDER BY j.priority_rank,
                         (SELECT MIN(il.expires_at)
                          FROM job_items ji
                          JOIN inventory_lots il ON il.lot_id = ji.lot_id
                          WHERE ji.job_id = j.job_id) IS NULL,
                         (SELECT MIN(il.expires_at)
                          FROM job_items ji
                          JOIN inventory_lots il ON il.lot_id = ji.lot_id
                          WHERE ji.job_id = j.job_id),
                         im.created_at,
                         j.job_id
                LIMIT %s
                FOR UPDATE SKIP LOCKED
                """,
                (self._sent_timeout_seconds, limit),
            )
            rows = cursor.fetchall()
            messages: list[RmfOutboxMessage] = []
            for row in rows:
                message_id = str(row[0])
                cursor.execute(
                    """
                    UPDATE integration_messages
                    SET state = 'sent', attempts = attempts + 1,
                        sent_at = NOW(6), next_attempt_at = NULL,
                        last_error = NULL
                    WHERE message_id = %s
                      AND (
                        state = 'pending'
                        OR (state = 'sent'
                            AND sent_at <= TIMESTAMPADD(
                              SECOND, -%s, NOW(6)))
                      )
                    """,
                    (message_id, self._sent_timeout_seconds),
                )
                if cursor.rowcount != 1:
                    continue
                messages.append(
                    RmfOutboxMessage(
                        message_id=message_id,
                        job_step_id=int(row[1]),
                        waypoint=str(row[2]),
                        fleet_name=str(row[3]),
                        robot_name=str(row[6]),
                        request_time_ms=int(row[4]),
                        attempts=int(row[5]) + 1,
                        state="sent",
                    )
                )
            connection.commit()
            return tuple(messages)
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    def acknowledge(
        self,
        message_id: str,
        job_step_id: int,
        acceptance: DispatchAcceptance,
    ) -> bool:
        if not acceptance.accepted or not acceptance.rmf_task_id:
            return False
        connection = self._connection_factory()
        cursor = connection.cursor()
        try:
            if acceptance.assignment is None:
                if not self._link_task_to_step(
                    cursor, job_step_id, acceptance
                ):
                    connection.rollback()
                    return False
            elif not self._project_assignment(
                cursor, job_step_id, acceptance
            ):
                connection.rollback()
                return False
            cursor.execute(
                """
                UPDATE integration_messages
                SET state = 'acknowledged',
                    external_reference = %s,
                    acknowledged_at = NOW(6),
                    last_error = NULL
                WHERE message_id = %s
                  AND job_step_id = %s
                  AND state IN ('sent','acknowledged')
                  AND (external_reference IS NULL OR external_reference = %s)
                """,
                (
                    acceptance.rmf_task_id,
                    message_id,
                    job_step_id,
                    acceptance.rmf_task_id,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return False
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def _link_task_to_step(
        cursor: Any,
        job_step_id: int,
        acceptance: DispatchAcceptance,
    ) -> bool:
        cursor.execute(
            """
            UPDATE job_steps
            SET rmf_task_id = %s,
                rmf_status = %s,
                rmf_status_observed_at = NOW(6)
            WHERE job_step_id = %s
              AND state IN ('pending','running')
              AND (rmf_task_id IS NULL OR rmf_task_id = %s)
            """,
            (
                acceptance.rmf_task_id,
                acceptance.rmf_status or "queued",
                job_step_id,
                acceptance.rmf_task_id,
            ),
        )
        return cursor.rowcount == 1

    @staticmethod
    def _project_assignment(
        cursor: Any,
        job_step_id: int,
        acceptance: DispatchAcceptance,
    ) -> bool:
        assignment = acceptance.assignment
        if assignment is None or assignment.task_id != acceptance.rmf_task_id:
            return False
        cursor.execute(
            """
            SELECT device_id
            FROM devices
            WHERE fleet_name = %s
              AND JSON_UNQUOTE(JSON_EXTRACT(
                capabilities, '$.rmf_robot_name')) = %s
              AND active = 1
            FOR UPDATE
            """,
            (assignment.fleet_name, assignment.robot_name),
        )
        device_row = cursor.fetchone()
        if device_row is None:
            return False
        device_id = str(device_row[0])

        cursor.execute(
            """
            SELECT r.reservation_id, r.job_step_id, js.rmf_task_id
            FROM reservations r
            LEFT JOIN job_steps js ON js.job_step_id = r.job_step_id
            WHERE r.device_id = %s
              AND r.state IN ('reserved','in_use')
              AND r.planned_start_at < FROM_UNIXTIME(%s / 1000.0)
              AND r.planned_end_at > FROM_UNIXTIME(%s / 1000.0)
            LIMIT 1
            """,
            (device_id, assignment.end_ms, assignment.start_ms),
        )
        overlap = cursor.fetchone()
        if overlap is not None and int(overlap[1]) != job_step_id:
            return False
        if overlap is not None:
            return str(overlap[2]) == acceptance.rmf_task_id

        cursor.execute(
            """
            UPDATE jobs j
            JOIN job_steps js ON js.job_id = j.job_id
            SET j.revision = j.revision + 1,
                j.assigned_mobile_id = %s,
                j.state = CASE WHEN j.state = 'queued'
                               THEN 'assigned' ELSE j.state END
            WHERE js.job_step_id = %s
              AND j.state IN ('queued','assigned','running')
              AND (j.assigned_mobile_id IS NULL
                   OR j.assigned_mobile_id = %s)
            """,
            (device_id, job_step_id, device_id),
        )
        if cursor.rowcount != 1:
            return False

        cursor.execute(
            """
            UPDATE job_steps
            SET assignment_revision = assignment_revision + 1,
                assigned_device_id = %s,
                rmf_task_id = %s,
                rmf_status = %s,
                rmf_status_observed_at = NOW(6)
            WHERE job_step_id = %s
              AND state IN ('pending','running')
              AND (assigned_device_id IS NULL OR assigned_device_id = %s)
              AND (rmf_task_id IS NULL OR rmf_task_id = %s)
            """,
            (
                device_id,
                acceptance.rmf_task_id,
                acceptance.rmf_status or "queued",
                job_step_id,
                device_id,
                acceptance.rmf_task_id,
            ),
        )
        if cursor.rowcount != 1:
            return False

        if overlap is None:
            cursor.execute(
                """
                INSERT INTO reservations (
                  job_id, job_step_id, device_id, reservation_mode,
                  state, planned_start_at, planned_end_at, expires_at)
                SELECT js.job_id, js.job_step_id, %s, 'time_slot',
                       'reserved',
                       FROM_UNIXTIME(%s / 1000.0),
                       FROM_UNIXTIME(%s / 1000.0),
                       TIMESTAMPADD(SECOND, 30,
                         FROM_UNIXTIME(%s / 1000.0))
                FROM job_steps js
                WHERE js.job_step_id = %s
                """,
                (
                    device_id,
                    assignment.start_ms,
                    assignment.end_ms,
                    assignment.end_ms,
                    job_step_id,
                ),
            )
            if cursor.rowcount != 1:
                return False
            cursor.execute(
                """
                INSERT INTO operation_events (
                  event_uuid, occurred_at, device_id, job_id, job_step_id,
                  severity, category, event_type, message, payload)
                SELECT UUID(), NOW(6), %s, js.job_id, js.job_step_id,
                       'info', 'rmf', 'RMF_ASSIGNMENT_RESERVED',
                       'Open-RMF assignment projected to Pinky time slot',
                       JSON_OBJECT(
                         'rmf_task_id', %s,
                         'rmf_robot_name', %s,
                         'planned_start_ms', %s,
                         'planned_end_ms', %s)
                FROM job_steps js
                WHERE js.job_step_id = %s
                """,
                (
                    device_id,
                    acceptance.rmf_task_id,
                    assignment.robot_name,
                    assignment.start_ms,
                    assignment.end_ms,
                    job_step_id,
                ),
            )
            if cursor.rowcount != 1:
                return False
        return True

    def mark_retry(self, message_id: str, reason: str) -> None:
        self._set_message_failure(
            message_id,
            state="pending",
            reason=reason,
            schedule_retry=True,
        )

    def mark_dead_letter(self, message_id: str, reason: str) -> None:
        self._set_message_failure(
            message_id,
            state="dead_letter",
            reason=reason,
            schedule_retry=False,
        )

    def knows_task(self, task_id: str) -> bool:
        connection = self._connection_factory()
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT 1 FROM job_steps WHERE rmf_task_id = %s LIMIT 1",
                (task_id,),
            )
            return cursor.fetchone() is not None
        finally:
            cursor.close()
            connection.close()

    def apply_task_update(self, update: RmfTaskUpdate) -> bool:
        connection = self._connection_factory()
        cursor = connection.cursor()
        try:
            if (
                update.fleet_name
                and update.robot_name
                and update.planned_start_ms is not None
                and update.planned_end_ms is not None
            ):
                try:
                    assignment = RmfAssignmentWindow(
                        update.task_id,
                        update.fleet_name,
                        update.robot_name,
                        update.planned_start_ms,
                        update.planned_end_ms,
                    )
                except ValueError:
                    connection.rollback()
                    return False
                acceptance = DispatchAcceptance(
                    True,
                    update.task_id,
                    update.rmf_status,
                    assignment=assignment,
                )
                if not self._project_assignment(
                    cursor, self._job_step_id(cursor, update.task_id), acceptance
                ):
                    connection.rollback()
                    return False
            cursor.execute(
                """
                UPDATE job_steps js
                LEFT JOIN devices d
                  ON d.fleet_name = %s
                 AND JSON_UNQUOTE(JSON_EXTRACT(
                   d.capabilities, '$.rmf_robot_name')) = %s
                 AND d.active = 1
                SET js.state = %s,
                    js.rmf_status = %s,
                    js.rmf_status_observed_at = FROM_UNIXTIME(%s / 1000.0),
                    js.assigned_device_id = COALESCE(
                      js.assigned_device_id, d.device_id)
                WHERE js.rmf_task_id = %s
                  AND js.state NOT IN ('succeeded','failed','cancelled')
                  AND (js.rmf_status_observed_at IS NULL
                    OR js.rmf_status_observed_at < FROM_UNIXTIME(%s / 1000.0))
                """,
                (
                    update.fleet_name,
                    update.robot_name,
                    update.step_state,
                    update.rmf_status,
                    update.observed_at_ms,
                    update.task_id,
                    update.observed_at_ms,
                ),
            )
            applied = cursor.rowcount == 1
            reservation_state = {
                "active": "in_use",
                "completed": "released",
                "failed": "cancelled",
                "canceled": "cancelled",
            }.get(update.rmf_status)
            if applied and reservation_state == "in_use":
                cursor.execute(
                    """
                    UPDATE reservations r
                    JOIN job_steps js ON js.job_step_id = r.job_step_id
                    SET r.state = %s,
                        r.entered_at = COALESCE(r.entered_at, NOW(6))
                    WHERE js.rmf_task_id = %s
                      AND r.state = 'reserved'
                    """,
                    (reservation_state, update.task_id),
                )
            elif applied and reservation_state in ("released", "cancelled"):
                cursor.execute(
                    """
                    UPDATE reservations r
                    JOIN job_steps js ON js.job_step_id = r.job_step_id
                    SET r.state = %s,
                        r.released_at = COALESCE(r.released_at, NOW(6)),
                        r.exited_at = CASE WHEN r.state = 'in_use'
                                          THEN COALESCE(r.exited_at, NOW(6))
                                          ELSE r.exited_at END
                    WHERE js.rmf_task_id = %s
                      AND r.state IN ('reserved','in_use')
                    """,
                    (reservation_state, update.task_id),
                )
            connection.commit()
            return applied
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def _job_step_id(cursor: Any, task_id: str) -> int:
        cursor.execute(
            """
            SELECT job_step_id
            FROM job_steps
            WHERE rmf_task_id = %s
            FOR UPDATE
            """,
            (task_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError("RMF task is not linked to a job step")
        return int(row[0])

    def _set_message_failure(
        self,
        message_id: str,
        *,
        state: str,
        reason: str,
        schedule_retry: bool,
    ) -> None:
        connection = self._connection_factory()
        cursor = connection.cursor()
        try:
            next_attempt = (
                "DATE_ADD(NOW(6), INTERVAL 2 SECOND)"
                if schedule_retry
                else "NULL"
            )
            cursor.execute(
                f"""
                UPDATE integration_messages
                SET state = %s,
                    next_attempt_at = {next_attempt},
                    last_error = %s
                WHERE message_id = %s
                  AND state IN ('sent','pending')
                """,
                (state, reason[:512], message_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()
