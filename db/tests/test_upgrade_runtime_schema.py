"""기존 개발 DB를 canonical runtime 상태 모델로 올리는 migration 테스트."""

import os
from pathlib import Path

import mysql.connector


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPOSITORY_ROOT / "db" / "archive" / "pre_physical_v1" / "007_upgrade_runtime_state_model.sql"
)
TEST_DATABASE = "trihouse_runtime_upgrade_test"


def _connect(database: str | None = None):
    options: dict[str, object] = {
        "host": os.environ.get("FMS_DB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("FMS_DB_PORT", "3307")),
        "user": os.environ.get("FMS_DB_ADMIN_USER", "root"),
        "password": os.environ.get("FMS_DB_ADMIN_PASSWORD", "test_root_password"),
        "autocommit": True,
    }
    if database is not None:
        options["database"] = database
    return mysql.connector.connect(**options)


def _execute_script(connection, sql: str) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute(sql)
        while cursor.nextset():
            pass
    finally:
        cursor.close()


def test_migration_preserves_rows_and_upgrades_runtime_state_contract() -> None:
    """구형 상태 행을 잃거나 최신 실행 추적 컬럼을 빠뜨리는 회귀를 막는다."""
    assert MIGRATION_PATH.exists(), "runtime state upgrade migration is missing"

    admin = _connect()
    try:
        cursor = admin.cursor()
        cursor.execute(f"DROP DATABASE IF EXISTS `{TEST_DATABASE}`")
        cursor.execute(f"CREATE DATABASE `{TEST_DATABASE}` CHARACTER SET utf8mb4")
        cursor.close()

        connection = _connect(TEST_DATABASE)
        try:
            _execute_script(
                connection,
                """
                CREATE TABLE jobs (
                  job_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                  state VARCHAR(24) NOT NULL DEFAULT 'pending',
                  completed_at DATETIME(6) NULL,
                  CONSTRAINT chk_jobs_state CHECK (state IN
                    ('pending','planned','running','waiting','blocked','completed',
                     'failed','cancelled','safety_hold'))
                ) ENGINE=InnoDB;
                CREATE TABLE job_steps (
                  job_step_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                  assigned_device_id VARCHAR(64) NULL,
                  state VARCHAR(24) NOT NULL DEFAULT 'pending',
                  rmf_task_id VARCHAR(128) NULL,
                  failure_reason VARCHAR(512) NULL,
                  CONSTRAINT chk_job_steps_state CHECK (state IN
                    ('pending','queued','running','succeeded','failed','on_hold',
                     'cancelled'))
                ) ENGINE=InnoDB;
                CREATE TABLE job_step_attempts (
                  attempt_uuid CHAR(36) NOT NULL PRIMARY KEY
                ) ENGINE=InnoDB;
                CREATE TABLE operation_events (
                  event_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                  event_uuid CHAR(36) NOT NULL,
                  occurred_at DATETIME(6) NOT NULL
                ) ENGINE=InnoDB;
                INSERT INTO jobs (state) VALUES ('pending'), ('blocked');
                INSERT INTO job_steps (state) VALUES ('queued'), ('on_hold');
                """,
            )
            migration = MIGRATION_PATH.read_text(encoding="utf-8").replace(
                "USE `trihouse_fms`;", f"USE `{TEST_DATABASE}`;"
            )
            _execute_script(connection, migration)

            cursor = connection.cursor()
            cursor.execute("SELECT state FROM jobs ORDER BY job_id")
            assert [row[0] for row in cursor.fetchall()] == ["queued", "held"]
            cursor.execute("SELECT state FROM job_steps ORDER BY job_step_id")
            assert [row[0] for row in cursor.fetchall()] == ["pending", "pending"]

            cursor.execute(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND (table_name, column_name) IN (
                    ('jobs', 'state_reason_code'),
                    ('jobs', 'updated_at'),
                    ('job_steps', 'assignment_revision'),
                    ('job_steps', 'rmf_task_id'),
                    ('operation_events', 'attempt_uuid'),
                    ('operation_events', 'correlation_uuid'))
                """,
                (TEST_DATABASE,),
            )
            assert set(cursor.fetchall()) == {
                ("jobs", "state_reason_code"),
                ("jobs", "updated_at"),
                ("job_steps", "assignment_revision"),
                ("job_steps", "rmf_task_id"),
                ("operation_events", "attempt_uuid"),
                ("operation_events", "correlation_uuid"),
            }
            cursor.close()
        finally:
            connection.close()
    finally:
        cursor = admin.cursor()
        cursor.execute(f"DROP DATABASE IF EXISTS `{TEST_DATABASE}`")
        cursor.close()
        admin.close()
