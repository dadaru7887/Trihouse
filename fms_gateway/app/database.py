"""MySQL connection management with the FMS time-zone invariant."""

from contextlib import contextmanager
from typing import Iterator

from .config import Settings


class Database:
    def __init__(self, settings: Settings):
        from mysql.connector.pooling import MySQLConnectionPool

        self._pool = MySQLConnectionPool(
            pool_name="trihouse_fms_gateway",
            pool_size=settings.pool_size,
            host=settings.host,
            port=settings.port,
            user=settings.user,
            password=settings.password,
            database=settings.database,
            autocommit=False,
        )

    @contextmanager
    def connection(self) -> Iterator[object]:
        connection = self._pool.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute("SET time_zone = '+09:00'")
            cursor.close()
            yield connection
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
