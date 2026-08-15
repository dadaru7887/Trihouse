#!/usr/bin/env python3
"""기존 SQLite 원장(robo_control.db)을 MySQL `robosapiens` 로 옮긴다.

MySQL 드라이버를 요구하지 않는다. SQLite를 읽어 `mysql` 클라이언트가 그대로
먹을 수 있는 SQL 스크립트를 만들고, 필요하면 그 클라이언트를 직접 호출한다.

  # 덤프만 만들기(내용을 눈으로 확인하고 싶을 때)
  python3 db/migrate_sqlite_to_mysql.py --out /tmp/robosapiens_data.sql

  # 만들어서 바로 적재
  python3 db/migrate_sqlite_to_mysql.py --load --user root --password

읽기는 항상 사본에서 한다. 관제센터가 떠 있는 상태로 돌려도 원본 DB(-wal 포함)를
건드리지 않는다.

주의: 생성되는 스크립트는 **전체 재적재**다. 대상 테이블을 비우고 다시 넣는다.
SQLite가 유일한 원장인 상태에서 한 번 넘길 때 쓰는 도구이며, MySQL이 원장이
된 뒤에 다시 돌리면 그 사이 쌓인 내용이 사라진다.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

DEFAULT_SQLITE = os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
    "robo_control",
    "robo_control.db",
)

DATABASE = "robosapiens"

# 부모 → 자식 순서. 적재 순서이자 삭제의 역순 기준이다.
TABLES = [
    "robots",
    "robot_telemetry",
    "workers",
    "lots",
    "stock_moves",
    "orders",
    "order_lines",
    "tasks",
    "task_steps",
    "events",
    "incidents",
    "counters",
]

# ISO8601 문자열로 저장돼 있던 열 → MySQL DATETIME(6)
DATETIME_COLUMNS = {
    "robots": {"registered_at", "retired_at"},
    "robot_telemetry": {"at"},
    "workers": {"registered_at", "retired_at"},
    "lots": {"expiry", "received_at"},
    "stock_moves": {"at"},
    "orders": {"created_at", "due_at", "closed_at"},
    "order_lines": set(),
    "tasks": {"expiry", "created_at", "assigned_at", "started_at", "ended_at"},
    "task_steps": set(),
    "events": {"at"},
    "incidents": {"at", "cleared_at"},
    "counters": set(),
}

# 0/1 로 저장된 논리값 → TINYINT(1). 값 검증에만 쓴다.
BOOL_COLUMNS = {
    "robots": {"reserve", "active"},
    "robot_telemetry": {"power_saving"},
    "workers": {"active"},
    "orders": {"expanded"},
    "incidents": {"active"},
}

_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[T ](\d{2}):(\d{2}):(\d{2})"
    r"(?:\.(\d{1,9}))?"
    r"(Z|[+-]\d{2}:?\d{2})?$"
)

_ESCAPES = {
    "\\": "\\\\",
    "'": "\\'",
    "\n": "\\n",
    "\r": "\\r",
    "\x00": "\\0",
    "\x1a": "\\Z",
}


class MigrationError(Exception):
    pass


def quote(s: str) -> str:
    """MySQL 문자열 리터럴. 기본 sql_mode(백슬래시 이스케이프 유효) 기준."""
    return "'" + "".join(_ESCAPES.get(ch, ch) for ch in s) + "'"


def to_mysql_datetime(value: str, where: str) -> str:
    """Dart `DateTime.toIso8601String()` 산출물을 DATETIME(6) 리터럴로."""
    m = _ISO.match(value.strip())
    if not m:
        raise MigrationError(f"{where}: 시각 형식을 해석할 수 없습니다 — {value!r}")
    y, mo, d, h, mi, s, frac, offset = m.groups()
    if offset not in (None, "", "Z", "+00:00", "+0000"):
        # 로컬 시각만 저장해 온 원장이다. 오프셋이 붙은 값이 나오면 조용히
        # 잘라내지 않고 멈춘다 — 시각이 어긋난 채 넘어가는 게 더 나쁘다.
        raise MigrationError(
            f"{where}: 타임존 오프셋이 붙은 값은 변환하지 않습니다 — {value!r}"
        )
    micro = (frac or "").ljust(6, "0")[:6]
    return f"'{y}-{mo}-{d} {h}:{mi}:{s}.{micro}'"


def literal(value, table: str, column: str) -> str:
    if value is None:
        return "NULL"
    where = f"{table}.{column}"
    if column in DATETIME_COLUMNS[table]:
        if not isinstance(value, str):
            raise MigrationError(f"{where}: 시각 열에 문자열이 아닌 값 — {value!r}")
        return to_mysql_datetime(value, where)
    if column in BOOL_COLUMNS.get(table, ()):
        if value not in (0, 1):
            raise MigrationError(f"{where}: 논리 열에 0/1 아닌 값 — {value!r}")
        return str(value)
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise MigrationError(f"{where}: 저장할 수 없는 실수 — {value!r}")
        return repr(value)
    if isinstance(value, str):
        return quote(value)
    if isinstance(value, (bytes, bytearray)):
        return "X'" + value.hex() + "'"
    raise MigrationError(f"{where}: 처리할 수 없는 타입 {type(value).__name__}")


def snapshot(source: str, workdir: str) -> str:
    """DB와 사이드카(-wal/-shm)를 사본으로 떠서 그 경로를 돌려준다."""
    if not os.path.exists(source):
        raise MigrationError(f"SQLite 파일이 없습니다: {source}")
    target = os.path.join(workdir, os.path.basename(source))
    for suffix in ("", "-wal", "-shm"):
        src = source + suffix
        if os.path.exists(src):
            shutil.copy2(src, target + suffix)
    return target


def columns_of(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    if not rows:
        raise MigrationError(f"원본에 {table} 테이블이 없습니다.")
    return [r[1] for r in rows]


def build(conn: sqlite3.Connection, batch: int) -> tuple[list[str], dict[str, int]]:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != 2:
        raise MigrationError(
            f"원본 스키마 버전이 2가 아닙니다(={version}). db/schema.sql 을 먼저 맞추세요."
        )

    out: list[str] = [
        "-- robo_control.db → robosapiens. db/migrate_sqlite_to_mysql.py 생성물.",
        "-- 전체 재적재: 아래 테이블의 기존 행을 지우고 다시 넣는다.",
        "SET sql_mode = '';",
        "SET NAMES utf8mb4;",
        "SET FOREIGN_KEY_CHECKS = 0;",
        "SET UNIQUE_CHECKS = 0;",
        f"USE `{DATABASE}`;",
        "START TRANSACTION;",
        "",
    ]
    for table in reversed(TABLES):
        out.append(f"DELETE FROM `{table}`;")
    out.append("")

    counts: dict[str, int] = {}
    for table in TABLES:
        cols = columns_of(conn, table)
        unknown = DATETIME_COLUMNS[table] - set(cols)
        if unknown:
            raise MigrationError(f"{table}: 원본에 없는 시각 열 {sorted(unknown)}")
        col_sql = ", ".join(f"`{c}`" for c in cols)
        select_sql = ", ".join('"' + c + '"' for c in cols)
        rows = conn.execute(f'SELECT {select_sql} FROM "{table}"').fetchall()
        counts[table] = len(rows)
        out.append(f"-- {table}: {len(rows)}행")
        for start in range(0, len(rows), batch):
            chunk = rows[start : start + batch]
            values = ",\n".join(
                "  ("
                + ", ".join(literal(v, table, c) for c, v in zip(cols, row))
                + ")"
                for row in chunk
            )
            out.append(f"INSERT INTO `{table}` ({col_sql}) VALUES\n{values};")
        out.append("")

    out += [
        "SET FOREIGN_KEY_CHECKS = 1;",
        "SET UNIQUE_CHECKS = 1;",
        "COMMIT;",
        "",
        "-- 적재 결과 확인",
        "SELECT "
        + ", ".join(
            f"(SELECT COUNT(*) FROM `{t}`) AS `{t}`" for t in TABLES
        )
        + ";",
        "",
    ]
    return out, counts


def mysql_argv(args) -> list[str]:
    argv = ["mysql"]
    if args.defaults_file:
        argv.append(f"--defaults-file={args.defaults_file}")
    if args.user:
        argv += ["-u", args.user]
    if args.host:
        argv += ["-h", args.host]
    if args.port:
        argv += ["-P", str(args.port)]
    if args.password:
        argv.append("-p")
    argv.append("--default-character-set=utf8mb4")
    return argv


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sqlite", default=DEFAULT_SQLITE, help="원본 SQLite 경로")
    ap.add_argument("--out", help="생성할 SQL 파일 경로(기본: 표준출력)")
    ap.add_argument("--load", action="store_true", help="생성한 SQL을 mysql로 적재")
    ap.add_argument("--schema", action="store_true",
                    help="적재 전에 db/schema.sql 을 먼저 적용")
    ap.add_argument("--user")
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--password", action="store_true", help="mysql -p (대화식 입력)")
    ap.add_argument("--defaults-file")
    ap.add_argument("--batch", type=int, default=200, help="INSERT 묶음 행 수")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="robosapiens-migrate-") as workdir:
        path = snapshot(args.sqlite, workdir)
        conn = sqlite3.connect(path)
        try:
            lines, counts = build(conn, args.batch)
        finally:
            conn.close()

    script = "\n".join(lines)
    total = sum(counts.values())

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(script)
        print(f"SQL 생성: {args.out} ({total}행)", file=sys.stderr)
    elif not args.load:
        sys.stdout.write(script)

    for table in TABLES:
        print(f"  {table:<18} {counts[table]:>6}", file=sys.stderr)

    if args.load:
        if args.schema:
            schema = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
            print(f"스키마 적용: {schema}", file=sys.stderr)
            with open(schema, "rb") as f:
                r = subprocess.run(mysql_argv(args), stdin=f)
            if r.returncode != 0:
                return r.returncode
        print(f"적재: {DATABASE} ({total}행)", file=sys.stderr)
        r = subprocess.run(mysql_argv(args), input=script.encode("utf-8"))
        if r.returncode != 0:
            return r.returncode
        print("완료", file=sys.stderr)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MigrationError as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)
