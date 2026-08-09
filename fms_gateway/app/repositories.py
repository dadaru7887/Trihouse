"""Queries used by the first control-system vertical slice."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Protocol
import uuid
from zoneinfo import ZoneInfo

from .database import Database


SEOUL = ZoneInfo("Asia/Seoul")


class FmsRepository(Protocol):
    def ping(self) -> bool: ...

    def list_devices(self) -> list[dict[str, object]]: ...

    def list_inventory(self) -> list[dict[str, object]]: ...

    def list_jobs(self) -> list[dict[str, object]]: ...

    def adjust_inventory(
        self,
        lot_id: int,
        quantity_delta: int,
        recorded_by: str,
        note: str | None,
        idempotency_key: str,
    ) -> dict[str, object]: ...


class InventoryLotNotFound(Exception):
    pass


class InventoryQuantityConflict(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


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

    @staticmethod
    def _lot(cursor, lot_id: int, *, for_update: bool = False):
        lock = " FOR UPDATE" if for_update else ""
        cursor.execute(
            """
            SELECT lot.lot_id, lot.lot_code, lot.product_code, lot.item_name,
                   lot.temperature_zone, loc.location_code, lot.expiry_date,
                   lot.available_qty, lot.reserved_qty, lot.state
            FROM inventory_lots lot
            LEFT JOIN locations loc ON loc.location_id = lot.location_id
            WHERE lot.lot_id = %s
            """ + lock,
            (lot_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def adjust_inventory(
        self,
        lot_id: int,
        quantity_delta: int,
        recorded_by: str,
        note: str | None,
        idempotency_key: str,
    ) -> dict[str, object]:
        event_uuid = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"trihouse:inventory-adjust:{idempotency_key}")
        )
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT payload FROM operation_events WHERE event_uuid = %s",
                    (event_uuid,),
                )
                existing = cursor.fetchone()
                if existing:
                    payload = existing["payload"]
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    expected = {
                        "lot_id": lot_id,
                        "quantity_delta": quantity_delta,
                        "recorded_by": recorded_by,
                    }
                    if any(payload.get(key) != value for key, value in expected.items()):
                        raise IdempotencyConflict
                    lot = self._lot(cursor, lot_id)
                    if lot is None:
                        raise InventoryLotNotFound
                    lot["available_qty"] = payload["quantity_after"]
                    return lot

                lot = self._lot(cursor, lot_id, for_update=True)
                if lot is None:
                    raise InventoryLotNotFound
                quantity_after = int(lot["available_qty"]) + quantity_delta
                if quantity_after < int(lot["reserved_qty"]):
                    raise InventoryQuantityConflict

                cursor.execute(
                    "UPDATE inventory_lots SET available_qty = %s WHERE lot_id = %s",
                    (quantity_after, lot_id),
                )
                cursor.execute(
                    """
                    INSERT INTO inventory_moves
                      (lot_id, move_type, quantity_delta, quantity_after,
                       reserved_delta, reserved_after, recorded_by, note)
                    VALUES (%s, 'adjustment', %s, %s, 0, %s, %s, %s)
                    """,
                    (
                        lot_id,
                        quantity_delta,
                        quantity_after,
                        lot["reserved_qty"],
                        recorded_by,
                        note,
                    ),
                )
                payload = {
                    "idempotency_key": idempotency_key,
                    "lot_id": lot_id,
                    "quantity_delta": quantity_delta,
                    "quantity_after": quantity_after,
                    "recorded_by": recorded_by,
                }
                cursor.execute(
                    """
                    INSERT INTO operation_events
                      (event_uuid, occurred_at, actor_worker_id, severity,
                       category, event_type, message, payload)
                    VALUES (%s, NOW(6), %s, 'info', 'inventory',
                            'inventory.adjusted', %s, %s)
                    """,
                    (
                        event_uuid,
                        recorded_by,
                        note or "inventory quantity adjusted",
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )
                connection.commit()
                lot["available_qty"] = quantity_after
                return lot
            finally:
                cursor.close()

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
