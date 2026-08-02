from __future__ import annotations

import datetime as dt

import mysql.connector
import pytest

from conftest import SEED_PATH, execute_sql_script


pytestmark = pytest.mark.integration


def test_schema_applies_cleanly(fresh_schema):
    """A deploy must create all 15 tables without an InnoDB key error."""
    assert fresh_schema is None


def _insert_location(mysql_db) -> None:
    mysql_db.execute(
        """
        INSERT INTO locations
          (location_code, name, location_type, temperature_zone)
        VALUES (%s, %s, %s, %s)
        """,
        ("TEST-SLOT", "Test slot", "slot", "ambient"),
    )


def _insert_lot(mysql_db) -> None:
    _insert_location(mysql_db)
    mysql_db.execute(
        """
        INSERT INTO inventory_lots
          (product_code, lot_code, item_name, temperature_zone, location_id,
           expiry_date, available_qty, reserved_qty)
        VALUES
          (%s, %s, %s, %s,
           (SELECT location_id FROM locations WHERE location_code = %s),
           %s, %s, %s)
        """,
        (
            "SKU-TEST",
            "LOT-TEST",
            "Test item",
            "ambient",
            "TEST-SLOT",
            dt.date(2027, 1, 1),
            10,
            2,
        ),
    )


def _insert_job(mysql_db, job_code: str, external_reference: str) -> None:
    mysql_db.execute(
        """
        INSERT INTO jobs
          (job_code, operation_type, external_reference)
        VALUES (%s, 'outbound', %s)
        """,
        (job_code, external_reference),
    )


def test_reserved_quantity_cannot_exceed_available(mysql_db):
    _insert_lot(mysql_db)

    with pytest.raises(mysql.connector.Error) as error:
        mysql_db.execute(
            """
            UPDATE inventory_lots
            SET reserved_qty = available_qty + 1
            WHERE lot_code = %s
            """,
            ("LOT-TEST",),
        )

    assert error.value.errno == 3819


def test_external_reference_is_idempotent(mysql_db):
    _insert_job(mysql_db, "JOB-REQUEST-001-A", "request-001")

    with pytest.raises(mysql.connector.IntegrityError) as error:
        _insert_job(mysql_db, "JOB-REQUEST-001-B", "request-001")

    assert error.value.errno == 1062


def test_mysql_session_uses_seoul_offset(mysql_db):
    row = mysql_db.one(
        "SELECT TIMEDIFF(NOW(6), UTC_TIMESTAMP(6)) AS timezone_offset"
    )

    assert str(row["timezone_offset"]) == "9:00:00"


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("jobs", "parent_job_id"),
        ("jobs", "revision"),
        ("jobs", "priority_rank"),
        ("inventory_moves", "reserved_delta"),
        ("inventory_moves", "reserved_after"),
        ("integration_messages", "next_attempt_at"),
        ("incidents", "acknowledged_by_worker_id"),
        ("incidents", "acknowledged_at"),
        ("operation_events", "actor_worker_id"),
    ],
)
def test_required_schema_column_exists(mysql_db, table, column):
    row = mysql_db.one(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.columns
        WHERE table_schema = 'trihouse_fms'
          AND table_name = %s
          AND column_name = %s
        """,
        (table, column),
    )

    assert row["count"] == 1


@pytest.mark.parametrize(
    ("table", "index"),
    [
        ("jobs", "uq_jobs_external_reference"),
        ("jobs", "idx_jobs_dispatch"),
        ("reservations", "idx_reservations_feature_expiry"),
        ("integration_messages", "idx_messages_delivery"),
        ("operation_events", "idx_events_occurred_at"),
    ],
)
def test_required_schema_index_exists(mysql_db, table, index):
    row = mysql_db.one(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.statistics
        WHERE table_schema = 'trihouse_fms'
          AND table_name = %s
          AND index_name = %s
        """,
        (table, index),
    )

    assert row["count"] >= 1


def test_artifact_uniqueness_keeps_full_uri_semantics(mysql_db):
    same_content_hash = "a" * 64
    mysql_db.execute(
        "INSERT INTO artifacts (artifact_type, storage_uri, sha256) VALUES (%s, %s, %s)",
        ("image", "s3://bucket/path-a", same_content_hash),
    )
    mysql_db.execute(
        "INSERT INTO artifacts (artifact_type, storage_uri, sha256) VALUES (%s, %s, %s)",
        ("image", "s3://bucket/path-b", same_content_hash),
    )

    with pytest.raises(mysql.connector.IntegrityError) as error:
        mysql_db.execute(
            "INSERT INTO artifacts (artifact_type, storage_uri, sha256) VALUES (%s, %s, %s)",
            ("image", "s3://bucket/path-a", same_content_hash),
        )

    assert error.value.errno == 1062


def test_development_seed_is_idempotent_and_complete(mysql_db):
    execute_sql_script(mysql_db.connection, SEED_PATH)
    execute_sql_script(mysql_db.connection, SEED_PATH)

    expected_counts = {
        "locations": 4,
        "workers": 2,
        "devices": 4,
        "device_states": 4,
        "inventory_lots": 2,
        "jobs": 1,
        "job_items": 1,
        "job_steps": 1,
    }
    actual_counts = {
        table: mysql_db.one(f"SELECT COUNT(*) AS count FROM `{table}`")["count"]
        for table in expected_counts
    }

    assert actual_counts == expected_counts
