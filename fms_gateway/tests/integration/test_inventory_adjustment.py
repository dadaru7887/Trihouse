
import pytest

from conftest import mysql_connection
from test_read_api import real_client


pytestmark = pytest.mark.integration


def scalar(sql: str) -> int:
    connection = mysql_connection(database="trihouse_fms")
    try:
        cursor = connection.cursor()
        cursor.execute(sql)
        value = cursor.fetchone()[0]
        cursor.close()
        return int(value)
    finally:
        connection.close()


def test_adjustment_updates_snapshot_and_appends_two_audit_records(seeded_schema):
    client = real_client()
    lot_id = client.get("/api/v1/inventory/lots").json()[0]["lot_id"]
    body = {
        "quantity_delta": -10,
        "recorded_by": "W-OP-01",
        "note": "cycle count",
    }

    response = client.post(
        f"/api/v1/inventory/lots/{lot_id}/adjust",
        headers={"Idempotency-Key": "adjust-dev-001"},
        json=body,
    )

    assert response.status_code == 200
    assert response.json()["available_qty"] == 90
    assert scalar("SELECT COUNT(*) FROM inventory_moves") == 1
    assert scalar("SELECT COUNT(*) FROM operation_events") == 1
    assert scalar(
        "SELECT available_qty FROM inventory_lots WHERE lot_code='LOT-DEV-001'"
    ) == 90


def test_repeating_idempotency_key_does_not_apply_twice(seeded_schema):
    client = real_client()
    lot_id = client.get("/api/v1/inventory/lots").json()[0]["lot_id"]
    request = {
        "headers": {"Idempotency-Key": "adjust-retry-001"},
        "json": {"quantity_delta": -7, "recorded_by": "W-OP-01"},
    }

    first = client.post(f"/api/v1/inventory/lots/{lot_id}/adjust", **request)
    second = client.post(f"/api/v1/inventory/lots/{lot_id}/adjust", **request)

    assert first.status_code == second.status_code == 200
    assert first.json()["available_qty"] == second.json()["available_qty"] == 93
    assert scalar("SELECT COUNT(*) FROM inventory_moves") == 1
    assert scalar("SELECT COUNT(*) FROM operation_events") == 1


def test_adjustment_below_reserved_quantity_is_atomic_conflict(seeded_schema):
    client = real_client()
    lot_id = client.get("/api/v1/inventory/lots").json()[0]["lot_id"]

    response = client.post(
        f"/api/v1/inventory/lots/{lot_id}/adjust",
        headers={"Idempotency-Key": "adjust-invalid-001"},
        json={"quantity_delta": -96, "recorded_by": "W-OP-01"},
    )

    assert response.status_code == 409
    assert scalar("SELECT COUNT(*) FROM inventory_moves") == 0
    assert scalar("SELECT COUNT(*) FROM operation_events") == 0
    assert scalar(
        "SELECT available_qty FROM inventory_lots WHERE lot_code='LOT-DEV-001'"
    ) == 100
