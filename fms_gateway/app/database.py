"""MySQL 연결 풀과 FMS 시간대 불변식을 관리하는 모듈."""

from contextlib import contextmanager
from typing import Iterator

from .config import Settings


class Database:
    """요청마다 풀 연결을 빌려주고 안전하게 반환하는 DB 경계."""

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
        """서울 시간대가 설정된 연결을 제공한다.

        호출자가 성공 경로에서 명시적으로 commit해야 한다. 예외가 발생했거나
        commit 없이 범위를 벗어나면 남은 트랜잭션을 rollback해 부분 저장을 막는다.
        """
        connection = self._pool.get_connection()
        cursor = connection.cursor()
        try:
            # MySQL NOW()/TIMESTAMP 변환과 애플리케이션의 Asia/Seoul 기준을 맞춘다.
            cursor.execute("SET time_zone = '+09:00'")
            cursor.close()
            yield connection
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
