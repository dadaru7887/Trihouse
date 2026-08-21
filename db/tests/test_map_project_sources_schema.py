"""Immutable, project-scoped map source and physical-feature schema contract."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "db" / "migrations" / "001_physical_v1_baseline.sql"


def _table(schema: str, name: str) -> str:
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS `?{name}`? \((.*?)\n\) ENGINE=InnoDB",
        schema,
        re.DOTALL,
    )
    assert match is not None, f"missing table: {name}"
    return match.group(1)


def test_source_table_is_project_scoped_without_global_hash_uniqueness() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    sources = _table(schema, "map_project_sources")

    for column in (
        "source_uuid",
        "project_id",
        "source_type",
        "file_name",
        "mime_type",
        "content_bytes",
        "sha256",
        "byte_size",
        "metadata",
        "created_at",
    ):
        assert re.search(rf"^\s*{column}\s+", sources, re.MULTILINE)
    assert "PRIMARY KEY (source_uuid)" in sources
    assert "KEY idx_map_project_sources_project (project_id, source_type, created_at)" in sources
    assert "FOREIGN KEY (project_id)" in sources
    assert "REFERENCES map_projects(project_id) ON DELETE CASCADE" in sources
    assert not re.search(r"UNIQUE KEY[^\n]*sha256", sources)


def test_source_table_constrains_types_and_content_integrity() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    sources = _table(schema, "map_project_sources")

    for source_type in (
        "slam_yaml",
        "slam_image",
        "floor_plan",
        "physical_features_import",
    ):
        assert f"'{source_type}'" in sources
    assert "sha256 REGEXP '^[0-9a-f]{64}$'" in sources
    assert "byte_size > 0" in sources


def test_map_features_accepts_only_the_planned_feature_types_and_revision_width() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    features = _table(schema, "map_features")

    assert re.search(r"map_revision\s+VARCHAR\(160\) NOT NULL", features)
    for feature_type in (
        "fiducial",
        "static_obstacle",
        "bottleneck",
        "door",
        "no_go_zone",
        "facility_footprint",
        "safety_zone",
        "speed_zone",
        "camera",
    ):
        assert f"'{feature_type}'" in features


def test_legacy_lane_table_is_documented_as_dormant_compatibility_ddl() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    lanes = _table(schema, "map_project_lanes")

    assert "dormant compatibility" in lanes.lower()
    assert "active draft" not in lanes.lower()
