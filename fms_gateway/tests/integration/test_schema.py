
import datetime as dt
import json
import re

import mysql.connector
import pytest

from conftest import QR_PAYLOAD_PATH, SEED_PATH, execute_sql_script


pytestmark = pytest.mark.integration


FMS_TABLES = {
    "artifacts",
    "device_states",
    "devices",
    "incidents",
    "integration_messages",
    "inventory_lots",
    "inventory_moves",
    "job_items",
    "job_step_attempts",
    "job_steps",
    "jobs",
    "location_recovery_profiles",
    "locations",
    "map_features",
    "map_project_files",
    "map_project_fleets",
    "map_project_lanes",
    "map_project_robots",
    "map_project_waypoints",
    "map_projects",
    "map_revisions",
    "operation_events",
    "reservations",
    "workers",
}
RECOVERY_TABLES = {"recovery_episodes", "recovery_steps"}


def _invalid_english_comment(value: object) -> bool:
    comment = str(value).strip()
    return not comment or not comment.isascii() or bool(re.search(r"[가-힣]", comment))


def test_schema_applies_cleanly(fresh_schema):
    """A deploy must create both FMS and recovery schemas cleanly."""
    assert fresh_schema is None


def test_recovery_memory_tables_are_created(mysql_db, recovery_mysql_db):
    fms_tables = mysql_db.all(
        """
        SELECT table_name AS table_name
        FROM information_schema.tables
        WHERE table_schema = 'trihouse_fms'
          AND table_type = 'BASE TABLE'
        """
    )
    recovery_tables = recovery_mysql_db.all(
        """
        SELECT table_name AS table_name
        FROM information_schema.tables
        WHERE table_schema = 'trihouse_recovery'
          AND table_type = 'BASE TABLE'
        """
    )

    assert {row["table_name"] for row in fms_tables} == FMS_TABLES
    assert {row["table_name"] for row in recovery_tables} == RECOVERY_TABLES


def test_all_tables_have_english_comments(mysql_db):
    tables = mysql_db.all(
        """
        SELECT
          table_schema AS schema_name,
          table_name AS table_name,
          table_comment AS table_comment
        FROM information_schema.tables
        WHERE table_schema IN ('trihouse_fms', 'trihouse_recovery')
          AND table_type = 'BASE TABLE'
        ORDER BY table_schema, table_name
        """
    )

    invalid = [
        f"{row['schema_name']}.{row['table_name']}"
        for row in tables
        if _invalid_english_comment(row["table_comment"])
    ]
    assert invalid == []


def test_all_columns_have_english_comments(mysql_db):
    columns = mysql_db.all(
        """
        SELECT
          table_schema AS schema_name,
          table_name AS table_name,
          column_name AS column_name,
          column_comment AS column_comment
        FROM information_schema.columns
        WHERE table_schema IN ('trihouse_fms', 'trihouse_recovery')
        ORDER BY table_schema, table_name, ordinal_position
        """
    )

    invalid = [
        f"{row['schema_name']}.{row['table_name']}.{row['column_name']}"
        for row in columns
        if _invalid_english_comment(row["column_comment"])
    ]
    assert invalid == []


def test_recovery_profile_is_unique_per_location(mysql_db):
    mysql_db.execute(
        """
        INSERT INTO locations
          (location_code, location_type, map_name, pose_x, pose_y, pose_yaw)
        VALUES ('SAFE-TEST-01', 'safe_node', 'warehouse', 1.0, 2.0, 0.0)
        """
    )
    location_id = mysql_db.one(
        "SELECT location_id FROM locations WHERE location_code = 'SAFE-TEST-01'"
    )["location_id"]
    mysql_db.execute(
        """
        INSERT INTO location_recovery_profiles
          (reference_node_uuid, location_id, map_revision, recovery_roles)
        VALUES (%s, %s, 'warehouse-v1', JSON_ARRAY('wait', 'rejoin'))
        """,
        ("00000000-0000-0000-0000-000000000101", location_id),
    )

    with pytest.raises(mysql.connector.IntegrityError) as error:
        mysql_db.execute(
            """
            INSERT INTO location_recovery_profiles
              (reference_node_uuid, location_id, map_revision, recovery_roles)
            VALUES (%s, %s, 'warehouse-v1', JSON_ARRAY('retreat'))
            """,
            ("00000000-0000-0000-0000-000000000102", location_id),
        )

    assert error.value.errno == 1062


def test_recovery_episode_requires_consistent_model_lineage(recovery_mysql_db):
    with pytest.raises(mysql.connector.Error) as error:
        recovery_mysql_db.execute(
            """
            INSERT INTO recovery_episodes
              (recovery_episode_uuid, device_id, map_name, map_revision, trigger_type,
               vlm_model_name, recovery_policy_name, recovery_policy_version,
               started_at, final_status)
            VALUES
              ('00000000-0000-0000-0000-000000000201', 'PINKY-01', 'warehouse',
               'warehouse-v1', 'blocked', 'vlm-a', 'policy-a', '1.0',
               '2026-08-09 12:00:00.000000', 'running')
            """
        )

    assert error.value.errno == 3819


def test_recovery_step_requires_observation_uri_and_hash_pair(recovery_mysql_db):
    recovery_mysql_db.execute(
        """
        INSERT INTO recovery_episodes
          (recovery_episode_uuid, device_id, map_name, map_revision, trigger_type,
           recovery_policy_name, recovery_policy_version, started_at, final_status)
        VALUES
          ('00000000-0000-0000-0000-000000000301', 'PINKY-01', 'warehouse',
           'warehouse-v1', 'blocked', 'policy-a', '1.0',
           '2026-08-09 12:00:00.000000', 'running')
        """
    )

    with pytest.raises(mysql.connector.Error) as error:
        recovery_mysql_db.execute(
            """
            INSERT INTO recovery_steps
              (recovery_episode_uuid, step_no, action_type, before_state_uri,
               outcome_class, execution_status, is_terminal, started_at)
            VALUES
              ('00000000-0000-0000-0000-000000000301', 1, 'wait',
               's3://recovery/before.json', 'safe', 'running', 0,
               '2026-08-09 12:00:01.000000')
            """
        )

    assert error.value.errno == 3819


def test_recovery_schema_has_no_foreign_keys_to_fms(recovery_mysql_db):
    cross_database_foreign_keys = recovery_mysql_db.one(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.key_column_usage
        WHERE table_schema = 'trihouse_recovery'
          AND referenced_table_schema = 'trihouse_fms'
        """
    )

    assert cross_database_foreign_keys["count"] == 0


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


def _apply_seed_twice(mysql_db):
    before = mysql_db.one("SELECT NOW(6) AS now")["now"]
    execute_sql_script(mysql_db.connection, SEED_PATH)
    execute_sql_script(mysql_db.connection, SEED_PATH)
    after = mysql_db.one("SELECT NOW(6) AS now")["now"]
    return before, after


def test_development_seed_is_idempotent_and_has_location_hierarchy(mysql_db):
    _apply_seed_twice(mysql_db)

    expected_warehouses = {
        "WH-AMB-01": ("상온창고", "ambient", "available"),
        "WH-CHL-01": ("냉장창고", "chilled", "available"),
        "WH-FRZ-01": ("냉동창고", "frozen", "available"),
    }
    warehouses = mysql_db.all(
        """
        SELECT location_code, name, temperature_zone, state, metadata,
               map_name, rmf_waypoint_name, pose_x, pose_y, pose_yaw
        FROM locations
        WHERE location_code IN ('WH-AMB-01', 'WH-CHL-01', 'WH-FRZ-01')
        ORDER BY location_code
        """
    )
    actual_warehouses = {
        row["location_code"]: (
            row["name"],
            row["temperature_zone"],
            row["state"],
        )
        for row in warehouses
    }
    assert actual_warehouses == expected_warehouses
    assert all(
        row[column] is None
        for row in warehouses
        for column in (
            "metadata",
            "map_name",
            "rmf_waypoint_name",
            "pose_x",
            "pose_y",
            "pose_yaw",
        )
    )

    expected_slots = {
        "AMB-L1-S01": ("WH-AMB-01", 1, 1, "occupied"),
        "AMB-L1-S02": ("WH-AMB-01", 1, 2, "available"),
        "AMB-L2-S01": ("WH-AMB-01", 2, 1, "occupied"),
        "AMB-L2-S02": ("WH-AMB-01", 2, 2, "occupied"),
        "CHL-L1-S01": ("WH-CHL-01", 1, 1, "occupied"),
        "CHL-L1-S02": ("WH-CHL-01", 1, 2, "occupied"),
        "CHL-L2-S01": ("WH-CHL-01", 2, 1, "occupied"),
        "CHL-L2-S02": ("WH-CHL-01", 2, 2, "occupied"),
        "FRZ-L1-S01": ("WH-FRZ-01", 1, 1, "occupied"),
        "FRZ-L1-S02": ("WH-FRZ-01", 1, 2, "occupied"),
        "FRZ-L2-S01": ("WH-FRZ-01", 2, 1, "occupied"),
        "FRZ-L2-S02": ("WH-FRZ-01", 2, 2, "occupied"),
    }
    slots = mysql_db.all(
        """
        SELECT child.location_code,
               parent.location_code AS parent_code,
               JSON_UNQUOTE(JSON_EXTRACT(child.metadata, '$.shelf_level')) AS shelf_level,
               JSON_UNQUOTE(JSON_EXTRACT(child.metadata, '$.slot_index')) AS slot_index,
               child.state, child.map_name, child.rmf_waypoint_name,
               child.pose_x, child.pose_y, child.pose_yaw
        FROM locations child
        JOIN locations parent ON parent.location_id = child.parent_location_id
        WHERE child.location_code REGEXP '^(AMB|CHL|FRZ)-L[12]-S0[12]$'
        ORDER BY child.location_code
        """
    )
    actual_slots = {
        row["location_code"]: (
            row["parent_code"],
            int(row["shelf_level"]),
            int(row["slot_index"]),
            row["state"],
        )
        for row in slots
    }
    assert actual_slots == expected_slots
    assert all(
        row[column] is None
        for row in slots
        for column in ("map_name", "rmf_waypoint_name", "pose_x", "pose_y", "pose_yaw")
    )


def test_development_seed_inventory_matches_qr_contract(mysql_db):
    before, after = _apply_seed_twice(mysql_db)

    expected_lots = {
        "LOT-AMB-ORANGE-001": ("SKU-ORANGE", "Orange", "ambient", "AMB-L2-S01", "2026-08-28", "0.200", 1, 0, "stored"),
        "LOT-AMB-STRAWBERRY-001": ("SKU-STRAWBERRY", "Strawberry", "ambient", "AMB-L2-S02", "2026-08-27", "0.250", 1, 0, "stored"),
        "LOT-AMB-MANDARIN-001": ("SKU-MANDARIN", "Mandarin", "ambient", "AMB-L1-S01", "2026-09-02", "0.120", 2, 0, "stored"),
        "LOT-CHL-COFFEE-001": ("SKU-COFFEE", "Coffee", "chilled", "CHL-L2-S01", "2026-10-31", "0.250", 1, 0, "stored"),
        "LOT-CHL-SANDWICH-001": ("SKU-SANDWICH", "Sandwich", "chilled", "CHL-L2-S02", "2026-09-10", "0.180", 2, 0, "stored"),
        "LOT-CHL-YOGURT-001": ("SKU-YOGURT", "Yogurt", "chilled", "CHL-L1-S01", "2026-09-30", "0.100", 2, 0, "stored"),
        "LOT-CHL-MILK-001": ("SKU-MILK", "Milk", "chilled", "CHL-L1-S02", "2026-09-20", "0.200", 1, 0, "stored"),
        "LOT-FRZ-PORKBELLY-001": ("SKU-PORKBELLY", "Pork belly", "frozen", "FRZ-L2-S01", "2027-08-13", "0.500", 2, 0, "stored"),
        "LOT-FRZ-DUMPLING-001": ("SKU-DUMPLING", "Dumpling", "frozen", "FRZ-L2-S02", "2027-08-20", "0.400", 1, 0, "stored"),
        "LOT-FRZ-ICEBAR-001": ("SKU-ICEBAR", "Ice bar", "frozen", "FRZ-L1-S01", "2027-08-25", "0.080", 2, 0, "stored"),
        "LOT-FRZ-ICECONE-001": ("SKU-ICECONE", "Ice cone", "frozen", "FRZ-L1-S02", "2027-08-31", "0.150", 2, 0, "stored"),
    }
    lots = mysql_db.all(
        """
        SELECT lot.lot_code, lot.product_code, lot.item_name,
               lot.temperature_zone, location.location_code,
               lot.expiry_date, lot.unit_weight_kg, lot.available_qty,
               lot.reserved_qty, lot.state, lot.received_at
        FROM inventory_lots lot
        JOIN locations location ON location.location_id = lot.location_id
        ORDER BY lot.lot_code
        """
    )
    actual_lots = {
        row["lot_code"]: (
            row["product_code"],
            row["item_name"],
            row["temperature_zone"],
            row["location_code"],
            str(row["expiry_date"]),
            str(row["unit_weight_kg"]),
            row["available_qty"],
            row["reserved_qty"],
            row["state"],
        )
        for row in lots
    }
    qr_lots = {
        entry["lot"]
        for entry in json.loads(QR_PAYLOAD_PATH.read_text(encoding="utf-8"))
    }

    assert actual_lots == expected_lots
    assert set(actual_lots) == qr_lots == set(expected_lots)
    assert all(before <= row["received_at"] <= after for row in lots)
    assert mysql_db.one(
        """
        SELECT COUNT(*) AS count
        FROM inventory_lots lot
        JOIN locations location ON location.location_id = lot.location_id
        WHERE location.location_code = 'AMB-L1-S02'
        """
    )["count"] == 0


def test_development_seed_smoke_job_uses_qr_inventory(mysql_db):
    _apply_seed_twice(mysql_db)

    smoke = mysql_db.one(
        """
        SELECT job.job_code, source.location_code AS source_code,
               item.product_code, item.requested_qty,
               item.verification_state, lot.lot_code
        FROM jobs job
        JOIN locations source ON source.location_id = job.source_location_id
        JOIN job_items item ON item.job_id = job.job_id
        JOIN inventory_lots lot ON lot.lot_id = item.lot_id
        WHERE job.job_code = 'JOB-DEV-001'
        """
    )

    assert smoke == {
        "job_code": "JOB-DEV-001",
        "source_code": "AMB-L2-S01",
        "product_code": "SKU-ORANGE",
        "requested_qty": 1,
        "verification_state": "pending",
        "lot_code": "LOT-AMB-ORANGE-001",
    }
