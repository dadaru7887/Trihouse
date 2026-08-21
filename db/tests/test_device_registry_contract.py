"""Static contracts for the canonical device registry and data migration."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "db" / "migrations" / "001_physical_v1_baseline.sql"
SEED_PATH = ROOT / "db" / "seeds" / "seed_dev.sql"
MIGRATION_PATH = ROOT / "db" / "archive" / "pre_physical_v1" / "005_normalize_device_registry.sql"

CANONICAL_IDS = {"PK_01", "PK_02", "OMX_01", "OMX_02"}
LEGACY_IDS = {"PINKY-01", "PINKY-02", "PK-01", "PK-02", "OMX-01", "OMX-02"}


def _device_foreign_keys(schema: str) -> set[tuple[str, str]]:
    references: set[tuple[str, str]] = set()
    for table_match in re.finditer(
        r"CREATE TABLE IF NOT EXISTS ([a-z_]+) \((.*?)\n\) ENGINE=InnoDB",
        schema,
        re.DOTALL,
    ):
        table, body = table_match.groups()
        references.update(
            (table, column)
            for column in re.findall(
                r"FOREIGN KEY \(([a-z_]+)\)\s+REFERENCES devices \(device_id\)",
                body,
            )
        )
    return references


def test_development_seed_uses_only_the_operational_device_registry() -> None:
    seed = SEED_PATH.read_text(encoding="utf-8")

    seeded_ids = set(
        re.findall(r"\('((?:PK|OMX)[_-][0-9]{2})', '(?:mobile|arm)'", seed)
    )
    assert seeded_ids == CANONICAL_IDS
    assert not any(legacy_id in seed for legacy_id in LEGACY_IDS)
    assert "'new_map_2_pinky'" in seed
    assert "'rmf_robot_name', 'PK_01'" in seed
    assert "'rmf_robot_name', 'PK_02'" in seed
    assert "'pinky_fleet'" not in seed
    assert "'omx_fleet'" not in seed
    assert re.search(r"\('OMX_01', 'arm'.*?, NULL,", seed)
    assert re.search(r"\('OMX_02', 'arm'.*?, NULL,", seed)


def test_project1_runtime_locations_use_real_rmf_waypoint_names() -> None:
    seed = SEED_PATH.read_text(encoding="utf-8")

    for waypoint in ("충전1", "충전2", "대기1", "대기3", "드랍오프1", "설비1", "설비2"):
        assert f"'{waypoint}'" in seed
    assert "'project1'" in seed
    assert "'warehouse', 'CHG_01'" not in seed


def test_migration_is_idempotent_data_only_and_maps_every_legacy_alias() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert not re.search(r"\b(?:ALTER|CREATE|DROP|TRUNCATE)\b", migration, re.IGNORECASE)
    assert "START TRANSACTION" in migration
    assert "COMMIT" in migration
    assert "ON DUPLICATE KEY UPDATE" in migration
    for legacy_id in LEGACY_IDS:
        assert f"'{legacy_id}'" in migration
    for canonical_id in CANONICAL_IDS:
        assert f"'{canonical_id}'" in migration
    assert "fleet_name = 'project1_pinky'" in migration
    assert "fleet_name = NULL" in migration
    assert "'$.rmf_robot_name', device_id" in migration


def test_existing_database_migration_upserts_project1_waypoint_registry() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    expected = {
        "A-SLOT-01": "픽업1",
        "OUT-DOCK-01": "드랍오프1",
        "CHG-01": "충전1",
        "CHG-02": "충전2",
        "IN-WAIT-01": "대기1",
        "NARROW-WAIT-01": "대기3",
        "OMX-WS-01": "설비1",
        "OMX-WS-02": "설비2",
    }
    for location_code, waypoint in expected.items():
        assert f"'{location_code}'" in migration
        assert f"'{waypoint}'" in migration
    assert "map_name = VALUES(map_name)" in migration
    assert "rmf_waypoint_name = VALUES(rmf_waypoint_name)" in migration


def test_migration_moves_all_device_foreign_keys_before_removing_aliases() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    foreign_keys = _device_foreign_keys(schema)

    assert foreign_keys
    for table, column in foreign_keys - {("device_states", "device_id")}:
        assert re.search(
            rf"UPDATE\s+`?{table}`?\s+SET\s+`?{column}`?\s*=\s*CASE",
            migration,
            re.IGNORECASE,
        ), f"migration does not preserve {table}.{column}"

    merge_position = migration.index("INSERT INTO device_states")
    child_delete_position = migration.index("DELETE FROM device_states")
    parent_delete_position = migration.index("DELETE FROM devices")
    assert merge_position < child_delete_position < parent_delete_position

    delete_predicates = re.findall(
        r"DELETE FROM (?:device_states|devices)\s+WHERE device_id IN\s*\((.*?)\);",
        migration,
        re.DOTALL,
    )
    assert len(delete_predicates) == 2
    for predicate in delete_predicates:
        for canonical_id in CANONICAL_IDS:
            assert f"'{canonical_id}'" not in predicate
