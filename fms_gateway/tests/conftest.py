from __future__ import annotations

import os
from pathlib import Path

import mysql.connector
import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPOSITORY_ROOT / "db" / "schema_mysql.sql"
SEED_PATH = REPOSITORY_ROOT / "db" / "seed_dev.sql"


def mysql_connection(*, database: str | None = None):
    options: dict[str, object] = {
        "host": os.environ.get("FMS_DB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("FMS_DB_PORT", "3307")),
        "user": os.environ.get("FMS_DB_USER", "root"),
        "password": os.environ.get("FMS_DB_PASSWORD", ""),
        "autocommit": False,
    }
    if database is not None:
        options["database"] = database
    return mysql.connector.connect(**options)


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
    connection = mysql_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("DROP DATABASE IF EXISTS trihouse_fms")
        cursor.close()
        execute_sql_script(connection, SCHEMA_PATH)
        connection.commit()
    finally:
        connection.close()

    yield

    connection = mysql_connection()
    try:
        cursor = connection.cursor()
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
def seeded_schema(fresh_schema):
    connection = mysql_connection(database="trihouse_fms")
    try:
        execute_sql_script(connection, SEED_PATH)
        connection.commit()
    finally:
        connection.close()

    yield
