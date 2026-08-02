"""Queries used by the first control-system vertical slice."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from .database import Database


SEOUL = ZoneInfo("Asia/Seoul")


class FmsRepository(Protocol):
    def ping(self) -> bool: ...

    def list_devices(self) -> list[dict[str, object]]: ...

    def list_inventory(self) -> list[dict[str, object]]: ...

    def list_jobs(self) -> list[dict[str, object]]: ...


def _seoul_datetimes(row: dict[str, object]) -> dict[str, object]:
    for key, value in row.items():
        if isinstance(value, datetime) and value.tzinfo is None:
            row[key] = value.replace(tzinfo=SEOUL)
    return row


class MySqlFmsRepository:
    def __init__(self, database: Database):
        self.database = database

    def _all(self, sql: str) -> list[dict[str, object]]:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(sql)
                return [_seoul_datetimes(dict(row)) for row in cursor.fetchall()]
            finally:
                cursor.close()

    def ping(self) -> bool:
        with self.database.connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT 1")
                return cursor.fetchone() == (1,)
            finally:
                cursor.close()

    def list_devices(self) -> list[dict[str, object]]:
        return self._all(
            """
            SELECT d.device_id, d.device_type, d.name, d.control_mode,
                   ds.state, ds.health, ds.battery_pct, ds.observed_at
            FROM devices d
            LEFT JOIN device_states ds ON ds.device_id = d.device_id
            WHERE d.active = 1
            ORDER BY d.device_type, d.device_id
            """
        )

    def list_inventory(self) -> list[dict[str, object]]:
        return self._all(
            """
            SELECT lot.lot_id, lot.lot_code, lot.product_code, lot.item_name,
                   lot.temperature_zone, loc.location_code, lot.expiry_date,
                   lot.available_qty, lot.reserved_qty, lot.state
            FROM inventory_lots lot
            LEFT JOIN locations loc ON loc.location_id = lot.location_id
            ORDER BY lot.expiry_date, lot.lot_id
            """
        )

    def list_jobs(self) -> list[dict[str, object]]:
        return self._all(
            """
            SELECT j.job_id, j.job_code, j.operation_type, j.priority, j.state,
                   j.due_at, j.assigned_mobile_id,
                   COUNT(DISTINCT ji.job_item_id) AS item_count,
                   COUNT(DISTINCT js.job_step_id) AS step_count
            FROM jobs j
            LEFT JOIN job_items ji ON ji.job_id = j.job_id
            LEFT JOIN job_steps js ON js.job_id = j.job_id
            GROUP BY j.job_id
            ORDER BY j.priority_rank, j.due_at, j.created_at
            """
        )
