
import os
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPOSITORY_ROOT / "db" / "schema_mysql.sql"
SEED_PATH = REPOSITORY_ROOT / "db" / "seed_dev.sql"


def _connection_options(
    *,
    user_variable: str,
    password_variable: str,
    default_user: str,
    default_password: str,
    database: str | None = None,
) -> dict[str, object]:
    options: dict[str, object] = {
        "host": os.environ.get("FMS_DB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("FMS_DB_PORT", "3307")),
        "user": os.environ.get(user_variable, default_user),
        "password": os.environ.get(password_variable, default_password),
        "autocommit": False,
    }
    if database is not None:
        options["database"] = database
    return options


def mysql_connection(*, database: str | None = None):
    """Connect as the least-privileged Gateway account used by the application."""
    import mysql.connector

    options = _connection_options(
        user_variable="FMS_DB_USER",
        password_variable="FMS_DB_PASSWORD",
        default_user="fms_gateway",
        default_password="test_gateway_password",
        database=database,
    )
    return mysql.connector.connect(**options)


def admin_mysql_connection(*, database: str | None = None):
    """Connect as the test-only administrator used for schema reset operations."""
    import mysql.connector

    options = _connection_options(
        user_variable="FMS_DB_ADMIN_USER",
        password_variable="FMS_DB_ADMIN_PASSWORD",
        default_user="root",
        default_password="test_root_password",
        database=database,
    )
    return mysql.connector.connect(**options)


def assert_disposable_test_database() -> None:
    """Refuse destructive fixture setup against the default development DB port."""
    host = os.environ.get("FMS_DB_HOST", "127.0.0.1")
    port = int(os.environ.get("FMS_DB_PORT", "3307"))
    explicitly_allowed = os.environ.get("FMS_DB_ALLOW_SCHEMA_RESET") == "1"
    local_test_endpoint = host in {"127.0.0.1", "localhost"} and port == 3307
    if not local_test_endpoint and not explicitly_allowed:
        raise RuntimeError(
            "Schema reset is allowed only on the local test DB at 127.0.0.1:3307. "
            "Set FMS_DB_ALLOW_SCHEMA_RESET=1 only for another disposable test DB."
        )


def execute_sql_script(connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    cursor = connection.cursor()
    try:
        cursor.execute(sql)
        while cursor.nextset():
            pass
    finally:
        cursor.close()


class DatabaseProbe:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params)
        finally:
            cursor.close()

    def one(self, sql: str, params: tuple[object, ...] = ()) -> dict[str, object]:
        cursor = self.connection.cursor(dictionary=True)
        try:
            cursor.execute(sql, params)
            row = cursor.fetchone()
            assert row is not None
            return row
        finally:
            cursor.close()

    def all(self, sql: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
        cursor = self.connection.cursor(dictionary=True)
        try:
            cursor.execute(sql, params)
            return list(cursor.fetchall())
        finally:
            cursor.close()


@pytest.fixture
def fresh_schema():
    assert_disposable_test_database()
    connection = admin_mysql_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("DROP DATABASE IF EXISTS trihouse_recovery")
        cursor.execute("DROP DATABASE IF EXISTS trihouse_fms")
        cursor.close()
        execute_sql_script(connection, SCHEMA_PATH)
        connection.commit()
    finally:
        connection.close()

    yield

    connection = admin_mysql_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("DROP DATABASE IF EXISTS trihouse_recovery")
        cursor.execute("DROP DATABASE IF EXISTS trihouse_fms")
        connection.commit()
        cursor.close()
    finally:
        connection.close()


@pytest.fixture
def mysql_db(fresh_schema):
    connection = mysql_connection(database="trihouse_fms")
    probe = DatabaseProbe(connection)
    try:
        probe.execute("SET time_zone = '+09:00'")
        yield probe
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def recovery_mysql_db(fresh_schema):
    connection = mysql_connection(database="trihouse_recovery")
    probe = DatabaseProbe(connection)
    try:
        probe.execute("SET time_zone = '+09:00'")
        yield probe
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def seeded_schema(fresh_schema):
    connection = mysql_connection(database="trihouse_fms")
    try:
        execute_sql_script(connection, SEED_PATH)
        connection.commit()
    finally:
        connection.close()

    yield
