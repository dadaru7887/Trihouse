"""P0 인수 e2e 공용 헬퍼.

`fms_gateway/tests/conftest.py`도 모듈 이름이 `conftest`라서, e2e 전용
헬퍼는 충돌하지 않는 이름을 쓴다. `sys.path` 준비는 같은 디렉터리의
`conftest.py`가 먼저 끝낸다.
"""

from __future__ import annotations

import pytest


def _mysql_reachable() -> bool:
    try:
        from conftest import mysql_connection  # type: ignore
    except Exception:
        return False
    try:
        connection = mysql_connection()
    except Exception:
        return False
    connection.close()
    return True


MYSQL_AVAILABLE = _mysql_reachable()

requires_mysql = pytest.mark.skipif(
    not MYSQL_AVAILABLE,
    reason="the P0 acceptance e2e needs the disposable MySQL at 127.0.0.1:3307",
)

__all__ = ["MYSQL_AVAILABLE", "requires_mysql"]
