"""Canonical 지도 편집·배포 스키마 계약."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "db" / "schema_mysql.sql"
MIGRATION_PATH = ROOT / "db" / "migrations" / "006_add_map_authoring_and_publication.sql"


def _table(sql: str, name: str) -> str:
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS `?{name}`? \((.*?)\n\) ENGINE=InnoDB",
        sql,
        re.DOTALL,
    )
    assert match is not None, f"missing table: {name}"
    return match.group(1)


def test_canonical_schema_owns_map_drafts_and_immutable_publications() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")

    projects = _table(schema, "map_projects")
    waypoints = _table(schema, "map_project_waypoints")
    lanes = _table(schema, "map_project_lanes")
    files = _table(schema, "map_project_files")
    revisions = _table(schema, "map_revisions")

    assert "draft_revision" in projects
    assert "UNIQUE KEY uq_map_projects_name (map_name)" in projects
    assert "waypoint_uuid" in waypoints
    assert "location_code" in waypoints
    assert "rmf_waypoint_name" in waypoints
    assert "map_x" in waypoints
    assert "map_y" in waypoints
    assert "map_yaw" in waypoints
    assert "UNIQUE KEY uq_map_waypoints_uuid (waypoint_uuid)" in waypoints
    assert "lane_uuid" in lanes
    assert "start_waypoint_uuid" in lanes
    assert "end_waypoint_uuid" in lanes
    assert "FOREIGN KEY (start_waypoint_uuid)" in lanes
    assert "file_name" in files
    assert "content" in files
    assert "PRIMARY KEY (project_id, file_name)" in files
    assert "map_revision" in revisions
    assert "building_sha256" in revisions
    assert "nav_graph_sha256" in revisions
    assert "world_sha256" in revisions
    assert "UNIQUE KEY uq_map_revisions_revision (map_revision)" in revisions


def test_canonical_schema_does_not_duplicate_ui_execution_ledgers() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")

    for legacy_table in ("rmf_ui_tasks", "rmf_ui_task_history", "robot_telemetry"):
        assert not re.search(
            rf"CREATE TABLE IF NOT EXISTS `?{legacy_table}`? \(", schema
        )


def test_existing_volume_migration_is_idempotent_and_contains_all_map_tables() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "USE `trihouse_fms`" in migration
    for table in (
        "map_projects",
        "map_project_waypoints",
        "map_project_lanes",
        "map_project_fleets",
        "map_project_robots",
        "map_project_files",
        "map_revisions",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration
    assert "DROP TABLE" not in migration.upper()
    assert "TRUNCATE" not in migration.upper()
