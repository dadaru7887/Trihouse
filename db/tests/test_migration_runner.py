from pathlib import Path

import pytest

from db.tools.apply_migrations import Migration, apply_pending, discover_migrations


class FakeDatabase:
    def __init__(self, applied=None):
        self.rows = dict(applied or {})
        self.executed: list[int] = []

    def applied_migrations(self):
        return dict(self.rows)

    def apply(self, migration: Migration):
        self.executed.append(migration.version)


def write(directory: Path, filename: str, sql: str = "SELECT 1;") -> None:
    (directory / filename).write_text(sql, encoding="utf-8")


def test_runner_applies_in_numeric_order_and_skips_matching_rows(tmp_path: Path) -> None:
    write(tmp_path, "001_base.sql")
    write(tmp_path, "002_next.sql")
    migrations = discover_migrations(tmp_path)
    database = FakeDatabase({1: (migrations[0].filename, migrations[0].sha256)})
    assert apply_pending(tmp_path, database) == [2]
    assert database.executed == [2]


def test_runner_refuses_a_changed_applied_file(tmp_path: Path) -> None:
    write(tmp_path, "001_base.sql")
    with pytest.raises(ValueError, match="checksum mismatch"):
        apply_pending(tmp_path, FakeDatabase({1: ("001_base.sql", "0" * 64)}))


def test_runner_refuses_a_numbering_gap(tmp_path: Path) -> None:
    write(tmp_path, "001_base.sql")
    write(tmp_path, "003_gap.sql")
    with pytest.raises(ValueError, match="contiguous"):
        discover_migrations(tmp_path)
