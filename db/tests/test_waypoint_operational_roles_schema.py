"""영문 Waypoint 운영 역할과 병목 feature의 canonical schema 계약."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (ROOT / "db" / "migrations" / "001_physical_v1_baseline.sql").read_text(encoding="utf-8")
SEED = (ROOT / "db" / "seeds" / "seed_dev.sql").read_text(encoding="utf-8")
MIGRATION_PATH = ROOT / "db" / "archive" / "pre_physical_v1" / "008_add_waypoint_operational_roles.sql"
LOADING_DOCK_MIGRATION_PATH = (
    ROOT / "db" / "archive" / "pre_physical_v1" / "011_unify_loading_dock_and_waiting_point.sql"
)
ROLE_GUIDE = (
    ROOT / "docs" / "architecture" / "waypoint-operational-roles.md"
).read_text(encoding="utf-8")


def _table(name: str) -> str:
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS `?{name}`? \((.*?)\n\) ENGINE=InnoDB",
        SCHEMA,
        re.DOTALL,
    )
    assert match is not None, f"missing table: {name}"
    return match.group(1)


def test_map_waypoints_store_searchable_operational_metadata() -> None:
    waypoints = _table("map_project_waypoints")

    assert "operational_role" in waypoints
    assert "temperature_zone" in waypoints
    assert "parent_location_code" in waypoints
    for role in (
        "safety_zone",
        "charging_station",
        "loading_dock",
        "bottleneck_waiting_point",
        "transit_waypoint",
        "parking_spot",
        "inspection_point",
        "workcell_station",
    ):
        assert role in waypoints
    for legacy_role in (
        "ambient_storage_access",
        "chilled_storage_access",
        "frozen_storage_access",
        "packing_handover",
    ):
        assert legacy_role not in waypoints


def test_existing_volume_migration_adds_roles_without_destructive_ddl() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "USE `trihouse_fms`" in migration
    assert "operational_role" in migration
    assert "temperature_zone" in migration
    assert "parent_location_code" in migration
    assert "DROP TABLE" not in migration.upper()
    assert "TRUNCATE" not in migration.upper()


def test_role_migration_is_restartable_and_removes_legacy_check_before_update() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "information_schema.COLUMNS" in migration
    assert "information_schema.TABLE_CONSTRAINTS" in migration
    assert "ELSE operational_role" in migration
    assert migration.index("DROP CHECK chk_map_waypoints_category") < migration.index(
        "UPDATE map_project_waypoints"
    )


def test_role_migration_does_not_depend_on_client_charset_for_legacy_values() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    expected_legacy_hex = {
        "EB8C80EAB8B0",  # waiting
        "ECA3BCECB0A8",  # parking
        "ED9988",  # home
        "ECB6A9ECA084",  # charging
        "ED94BDEC9785",  # pickup
        "EB939CEB9E8DEC98A4ED9484",  # dropoff (legacy spelling)
        "EB939CEBA1ADEC98A4ED9484",  # dropoff (alternate spelling)
        "EC84A4EBB984",  # equipment
        "EC9DBCEBB098",  # generic waypoint
    }

    assert "HEX(category)" in migration
    for value in expected_legacy_hex:
        assert value in migration


def test_bottleneck_uses_existing_map_feature_contract() -> None:
    features = _table("map_features")

    assert "'bottleneck'" in features
    assert "geometry" in features
    assert "properties" in features


def test_canonical_warehouse_display_names_are_english() -> None:
    for name in ("Ambient Storage", "Chilled Storage", "Frozen Storage"):
        assert name in SEED
    for legacy in ("'상온창고'", "'냉장창고'", "'냉동창고'"):
        assert legacy not in SEED


def test_gazebo_namespace_is_unique_per_project() -> None:
    robots = _table("map_project_robots")
    assert "UNIQUE KEY uq_map_robots_gz_name (project_id, gz_name)" in robots
    migration = (
        ROOT / "db" / "archive" / "pre_physical_v1" / "009_unique_project_robot_gz_name.sql"
    ).read_text(encoding="utf-8")
    assert "uq_map_robots_gz_name" in migration


def test_map_name_is_a_single_safe_identity_in_schema_and_migration() -> None:
    projects = _table("map_projects")
    assert "chk_map_projects_name" in projects
    assert "^[A-Za-z0-9_][A-Za-z0-9_-]{0,94}$" in projects
    migration = (
        ROOT / "db" / "archive" / "pre_physical_v1" / "010_enforce_canonical_map_name.sql"
    ).read_text(encoding="utf-8")
    assert "chk_map_projects_name" in migration
    assert "REGEXP" in migration
    assert "DROP TABLE" not in migration.upper()


def test_loading_dock_is_direction_neutral_and_waiting_point_is_supported() -> None:
    locations = _table("locations")
    waypoints = _table("map_project_waypoints")
    migration = (
        ROOT / "db" / "archive" / "pre_physical_v1" / "011_unify_loading_dock_and_waiting_point.sql"
    ).read_text(encoding="utf-8")

    assert "'loading_dock'" in locations
    assert "'bottleneck_waiting_point'" in waypoints
    assert "operational_role = 'loading_dock'" in migration
    assert "location_type = 'loading_dock'" in migration
    assert "location_type IN ('inbound_dock','outbound_dock')" in migration
    assert "'PACKING-01', 'Packing Station'" in migration
    assert "DROP TABLE" not in migration.upper()


def test_existing_volume_guide_applies_role_schema_before_loading_dock_data() -> None:
    """011 reads operational_role, so the documented command must run 008 first."""

    role_position = ROLE_GUIDE.index(
        "db/archive/pre_physical_v1/008_add_waypoint_operational_roles.sql"
    )
    loading_dock_position = ROLE_GUIDE.index(
        "db/archive/pre_physical_v1/011_unify_loading_dock_and_waiting_point.sql"
    )

    assert role_position < loading_dock_position
    assert "Requires migration 008" in LOADING_DOCK_MIGRATION_PATH.read_text(
        encoding="utf-8"
    )
