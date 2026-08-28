"""005 migration keeps the recovery proposal schema loadable and contiguous."""

from pathlib import Path

from db.tools.apply_migrations import discover_migrations


MIGRATION_DIR = Path(__file__).resolve().parents[1] / "migrations"
MIGRATION = MIGRATION_DIR / "005_recovery_skill_selection.sql"


def test_migration_set_stays_contiguous_after_adding_skill_selection() -> None:
    versions = [migration.version for migration in discover_migrations(MIGRATION_DIR)]

    assert versions == list(range(1, len(versions) + 1))
    assert versions[-1] == 5


def test_migration_adds_a_nullable_json_column_guarded_by_a_check() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "USE `trihouse_recovery`;" in sql
    assert "ALTER TABLE recovery_proposals" in sql
    assert "ADD COLUMN skill_selection JSON NULL" in sql
    assert "JSON_TYPE(skill_selection) = 'OBJECT'" in sql


def test_baseline_and_earlier_recovery_migrations_are_untouched() -> None:
    baseline = (MIGRATION_DIR / "004_recovery_proposals_and_approvals.sql").read_text(encoding="utf-8")

    assert "skill_selection" not in baseline
