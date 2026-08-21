"""Validate immutable numbered migration files and apply each pending version in order."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Protocol


MIGRATION_NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    filename: str
    sha256: str
    sql: str


class MigrationDatabase(Protocol):
    def applied_migrations(self) -> dict[int, tuple[str, str]]: ...
    def apply(self, migration: Migration) -> None: ...


def discover_migrations(directory: Path) -> list[Migration]:
    migrations: list[Migration] = []
    for path in sorted(directory.glob("[0-9][0-9][0-9]_*.sql")):
        match = MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            continue
        content = path.read_bytes()
        migrations.append(Migration(
            version=int(match.group(1)),
            filename=path.name,
            sha256=hashlib.sha256(content).hexdigest(),
            sql=content.decode("utf-8"),
        ))
    versions = [migration.version for migration in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise ValueError(f"migration versions must be contiguous from 001: {versions}")
    return migrations


def apply_pending(directory: Path, database: MigrationDatabase) -> list[int]:
    migrations = discover_migrations(directory)
    applied = database.applied_migrations()
    known = {migration.version: migration for migration in migrations}
    if set(applied) - set(known):
        raise ValueError("database contains a migration version missing from the source tree")
    for version, (filename, digest) in applied.items():
        migration = known[version]
        if (filename, digest) != (migration.filename, migration.sha256):
            raise ValueError(f"migration {version:03d} filename or checksum mismatch")
    completed: list[int] = []
    for migration in migrations:
        if migration.version in applied:
            continue
        expected = max(applied, default=0) + 1
        if migration.version != expected:
            raise ValueError(f"cannot apply migration {migration.version:03d} before {expected:03d}")
        database.apply(migration)
        applied[migration.version] = (migration.filename, migration.sha256)
        completed.append(migration.version)
    return completed
