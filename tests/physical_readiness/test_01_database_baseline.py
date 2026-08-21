import re
from pathlib import Path

from .conftest import BASELINE_SQL, REPOSITORY_ROOT


def _compose_text(filename: str) -> str:
    return (REPOSITORY_ROOT / filename).read_text(encoding="utf-8")


def test_physical_baseline_is_the_only_active_numbered_migration():
    migrations = sorted(
        path.name for path in (REPOSITORY_ROOT / "db/migrations").glob("[0-9][0-9][0-9]_*.sql")
    )

    assert migrations == ["001_physical_v1_baseline.sql"]
    assert BASELINE_SQL.is_file()


def test_pre_baseline_upgrade_history_is_archived():
    archive = REPOSITORY_ROOT / "db/archive/pre_physical_v1"
    archived_versions = {
        int(match.group(1))
        for path in archive.glob("[0-9][0-9][0-9]_*.sql")
        if (match := re.match(r"(\d{3})_", path.name))
    }

    assert archived_versions == set(range(4, 13))


def test_baseline_defines_a_checksum_migration_ledger():
    sql = BASELINE_SQL.read_text(encoding="utf-8")

    assert re.search(r"CREATE TABLE IF NOT EXISTS\s+schema_migrations", sql, re.IGNORECASE)
    for column in ("version", "filename", "sha256", "applied_at"):
        assert re.search(rf"\b{column}\b", sql)


def test_compose_database_stacks_mount_the_baseline():
    expected = "./db/migrations/001_physical_v1_baseline.sql:/docker-entrypoint-initdb.d/001_schema.sql:ro"
    ledger = "./db/init/002_record_physical_baseline.sh:/docker-entrypoint-initdb.d/002_record_physical_baseline.sh:ro"

    for filename in ("compose.yaml", "compose.db.yaml", "compose.db_test.yaml"):
        assert expected in _compose_text(filename)
        assert ledger in _compose_text(filename)
