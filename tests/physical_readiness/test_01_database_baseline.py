import re
from pathlib import Path

from .conftest import BASELINE_SQL, REPOSITORY_ROOT


def _compose_text(filename: str) -> str:
    return (REPOSITORY_ROOT / filename).read_text(encoding="utf-8")


def test_physical_baseline_starts_a_contiguous_numbered_migration_chain():
    migrations = sorted(
        path.name for path in (REPOSITORY_ROOT / "db/migrations").glob("[0-9][0-9][0-9]_*.sql")
    )
    versions = [int(filename[:3]) for filename in migrations]

    assert migrations[0] == "001_physical_v1_baseline.sql"
    assert versions == list(range(1, len(versions) + 1))
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
    migrations = "./db/migrations:/trihouse-migrations:ro"
    runner = "./db/init/003_apply_physical_migrations.sh:/docker-entrypoint-initdb.d/003_apply_physical_migrations.sh:ro"
    recovery_grant = "./db/init/003_grant_gateway_recovery.sh:/docker-entrypoint-initdb.d/005_grant_gateway_recovery.sh:ro"

    for filename in ("compose.yaml", "compose.db.yaml", "compose.db_test.yaml"):
        assert expected in _compose_text(filename)
        assert ledger in _compose_text(filename)
        assert migrations in _compose_text(filename)
        assert runner in _compose_text(filename)
        assert recovery_grant in _compose_text(filename)
