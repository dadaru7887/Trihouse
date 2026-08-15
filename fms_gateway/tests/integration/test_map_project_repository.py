import hashlib
import json
import os
from pathlib import Path
import uuid

import pytest

from fms_gateway.app.config import Settings, get_settings
from fms_gateway.app.database import Database
from fms_gateway.app.repositories import (
    MapDraftRevisionConflict,
    MapProjectSourceValidationError,
    MySqlFmsRepository,
)


ROOT = Path(__file__).resolve().parents[3]
PHYSICAL_JSONL = (
    ROOT
    / "control_ui"
    / "rmf_control_ui"
    / "data"
    / "import"
    / "trihouse_test_01_physical_features.jsonl"
)


def _repository() -> MySqlFmsRepository:
    get_settings.cache_clear()
    return MySqlFmsRepository(Database(get_settings()))


def _race_repository() -> MySqlFmsRepository:
    return MySqlFmsRepository(
        Database(
            Settings(
                host=os.environ.get("FMS_DB_HOST", "127.0.0.1"),
                port=int(os.environ.get("FMS_DB_PORT", "3307")),
                user=os.environ.get("FMS_DB_USER", "fms_gateway"),
                password=os.environ.get(
                    "FMS_DB_PASSWORD", "test_gateway_password"
                ),
                database="trihouse_fms",
                pool_size=2,
            )
        )
    )


def _cyclic_metadata() -> dict[str, object]:
    metadata: dict[str, object] = {}
    metadata["cycle"] = metadata
    return metadata


def _project() -> dict:
    return {
        "format_version": 2,
        "payload": {
            "format": "robosapiens-map-project",
            "version": 2,
            "mapName": "project1",
            "waypoints": [
                {"point": [200.0, 200.0], "mapPose": [2.0, -2.0, 0.0], "name": "충전1", "category": "충전"},
                {"point": [500.0, 200.0], "mapPose": [5.0, -2.0, 0.0], "name": "대기1", "category": "대기"},
            ],
            "laneDirections": [
                {"start": [200.0, 200.0], "end": [500.0, 200.0], "direction": "양방향"}
            ],
        },
        "building_yaml": "name: project1\nlevels:\n  L1: {}\n",
        "building_yaml_name": "project1.building.yaml",
        "files": [],
        "fleet": {"fleet_name": "project1_pinky", "settings": {}},
        "robots": [
            {
                "robot_id": "PK_01",
                "seq": 1,
                "display_name": "Pinky 1",
                "model": "Pinky-Pro",
                "kind": "mobile",
                "data_source": "gazebo",
                "gz_name": "pinky_01",
                "zones": ["ambient"],
                "charger_waypoint_name": "충전1",
                "spawn_x": 2.0,
                "spawn_y": 2.0,
                "spawn_heading": 0.0,
            }
        ],
    }


def test_mysql_project_publish_updates_authoring_and_operational_projection(
    mysql_db,
):
    get_settings.cache_clear()
    repository = MySqlFmsRepository(Database(get_settings()))

    saved = repository.save_map_project("project1", _project(), None)
    assert saved["draft_revision"] == 1
    assert saved["payload"]["waypoints"][0]["locationCode"] == "CHG-01"

    building = _project()["building_yaml"]
    nav_graph = """levels:\n  L1:\n    vertices:\n      - [2.0, -2.0, {name: 충전1}]\n      - [5.0, -2.0, {name: 대기1}]\n"""
    world = "<sdf version='1.9'></sdf>"
    hashes = {
        "building_sha256": hashlib.sha256(building.encode()).hexdigest(),
        "nav_graph_sha256": hashlib.sha256(nav_graph.encode()).hexdigest(),
        "world_sha256": hashlib.sha256(world.encode()).hexdigest(),
    }
    revision = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    publication = repository.publish_map_project(
        "project1",
        {
            "map_revision": "project1:" + revision,
            **hashes,
            "building_yaml_content": building,
            "nav_graph_yaml_content": nav_graph,
            "world_content": world,
            "published_by": "W-OP-01",
            "manifest": {"project": "project1"},
        },
    )
    assert publication["state"] == "published"

    charger = mysql_db.one(
        "SELECT map_name, rmf_waypoint_name, pose_x, pose_y, metadata "
        "FROM locations WHERE location_code = 'CHG-01'"
    )
    assert charger["map_name"] == "project1"
    assert charger["rmf_waypoint_name"] == "충전1"
    assert charger["pose_x"] == 2.0
    assert charger["pose_y"] == -2.0

    robot = mysql_db.one(
        "SELECT fleet_name, home_location_id, current_location_id, control_mode "
        "FROM devices WHERE device_id = 'PK_01'"
    )
    assert robot["fleet_name"] == "project1_pinky"
    assert robot["home_location_id"] == mysql_db.one(
        "SELECT location_id FROM locations WHERE location_code = 'CHG-01'"
    )["location_id"]
    assert robot["current_location_id"] is None
    assert robot["control_mode"] == "automatic"


def test_mysql_draft_discards_legacy_lanes_without_using_compatibility_table(
    mysql_db,
):
    repository = _repository()

    saved = repository.save_map_project("project1", _project(), None)

    assert "laneDirections" not in saved["payload"]
    assert saved["lane_count"] == 0
    assert mysql_db.one("SELECT lane_count FROM map_projects")["lane_count"] == 0
    assert mysql_db.one("SELECT COUNT(*) AS count FROM map_project_lanes")["count"] == 0


def test_mysql_project_sources_match_in_memory_scope_and_lifecycle(mysql_db):
    repository = _repository()
    for map_name in ("source_project_a", "source_project_b"):
        repository.save_map_project(map_name, _project(), None)
    source = {
        "source_type": "physical_features_import",
        "file_name": "physical.jsonl",
        "mime_type": "application/x-ndjson",
        "content_bytes": b"same-content",
        "metadata": {
            "schema_version": 1,
            "nested": {"value": "original"},
            "items": [1, 2],
        },
    }

    first = repository.store_map_project_source("source_project_a", source)
    second = repository.store_map_project_source("source_project_b", source)

    assert first["source_uuid"] != second["source_uuid"]
    assert first["sha256"] == second["sha256"]
    first["metadata"]["nested"]["value"] = "caller-mutation"
    stored = repository.get_map_project_source(
        "source_project_a", first["source_uuid"]
    )
    assert stored is not None
    assert stored["metadata"]["nested"]["value"] == "original"
    assert (
        repository.get_map_project_source("source_project_b", first["source_uuid"])
        is None
    )

    repository.delete_map_project("source_project_a")
    repository.save_map_project("source_project_a", _project(), None)
    assert (
        repository.get_map_project_source("source_project_a", first["source_uuid"])
        is None
    )
    assert mysql_db.one(
        "SELECT COUNT(*) AS count FROM map_project_sources WHERE source_uuid = %s",
        (first["source_uuid"],),
    )["count"] == 0


@pytest.mark.parametrize(
    "metadata_factory",
    [
        lambda: {"bad": object()},
        lambda: {"bad": float("nan")},
        lambda: {1: "non-string-key"},
        _cyclic_metadata,
    ],
)
def test_mysql_project_source_metadata_uses_stable_domain_errors(
    mysql_db, metadata_factory
):
    repository = _repository()
    repository.save_map_project("source_project", _project(), None)

    with pytest.raises(MapProjectSourceValidationError, match="metadata"):
        repository.store_map_project_source(
            "source_project",
            {
                "source_type": "physical_features_import",
                "file_name": "physical.jsonl",
                "mime_type": "application/x-ndjson",
                "content_bytes": b"content",
                "metadata": metadata_factory(),
            },
        )


def _mysql_source_with_metadata(metadata: dict[str, object]) -> dict[str, object]:
    return {
        "source_type": "physical_features_import",
        "file_name": "physical.jsonl",
        "mime_type": "application/x-ndjson",
        "content_bytes": b"content",
        "metadata": metadata,
    }


@pytest.mark.parametrize("value", [-(2**53 - 1), 2**53 - 1])
def test_mysql_source_metadata_round_trips_safe_integer_boundaries(
    mysql_db, value: int
) -> None:
    repository = _repository()
    repository.save_map_project("source_project", _project(), None)

    stored = repository.store_map_project_source(
        "source_project",
        _mysql_source_with_metadata(
            {"nested": {"value": value}, "enabled": True}
        ),
    )
    loaded = repository.get_map_project_source(
        "source_project", stored["source_uuid"]
    )

    assert loaded is not None
    assert loaded["metadata"]["nested"]["value"] == value
    assert type(loaded["metadata"]["nested"]["value"]) is int
    assert loaded["metadata"]["enabled"] is True


@pytest.mark.parametrize("value", [-(2**53), 2**53, 10**400])
def test_mysql_source_metadata_rejects_integers_outside_safe_range_before_sql(
    mysql_db, value: int
) -> None:
    repository = _repository()
    repository.save_map_project("source_project", _project(), None)

    with pytest.raises(
        MapProjectSourceValidationError,
        match=r"metadata \$\.nested\.value.*safe integer",
    ):
        repository.store_map_project_source(
            "source_project",
            _mysql_source_with_metadata({"nested": {"value": value}}),
        )

    assert mysql_db.one("SELECT COUNT(*) AS count FROM map_project_sources")[
        "count"
    ] == 0


def _public_records() -> tuple[list[dict], list[dict]]:
    from fms_gateway.app.map_deployment import physical_import_to_public_records
    from fms_gateway.app.physical_features import PhysicalFeatureImporter

    return physical_import_to_public_records(
        PhysicalFeatureImporter().parse(PHYSICAL_JSONL.read_bytes())
    )


def _public_draft(
    profile_hash: str,
    source_uuids: dict[str, str],
    *,
    extra_waypoints: list[dict] | None = None,
) -> dict:
    waypoints, features = _public_records()
    return {
        "format_version": 1,
        "source_uuids": source_uuids,
        "waypoints": waypoints + (extra_waypoints or []),
        "features": features,
        "runtime_profile_hash": profile_hash,
    }


def _source(
    source_type: str,
    content: bytes,
    mime_type: str,
    file_name: str,
    *,
    metadata: dict | None = None,
) -> dict:
    return {
        "source_uuid": str(uuid.uuid4()),
        "source_type": source_type,
        "file_name": file_name,
        "mime_type": mime_type,
        "content_bytes": content,
        "metadata": metadata,
    }


def test_mysql_public_save_promotes_sources_and_draft_in_one_transaction(mysql_db):
    from fms_gateway.app.runtime_profiles import RuntimeProfileProvider

    repository = _repository()
    profile_hash = RuntimeProfileProvider(ROOT).load()["profile_hash"]
    physical_waypoints, physical_features = _public_records()
    source = _source(
        "physical_features_import",
        PHYSICAL_JSONL.read_bytes(),
        "application/x-ndjson",
        "renamed-source.data",
        metadata={"waypoints": physical_waypoints, "features": physical_features},
    )
    saved = repository.save_public_map_draft(
        "trihouse_test_01",
        _public_draft(
            profile_hash,
            {"physical_features_import": source["source_uuid"]},
        ),
        expected_revision=0,
        staged_sources=[source],
    )
    assert saved["draft_revision"] == 1
    assert saved["source_uuids"]["physical_features_import"] == source["source_uuid"]
    assert mysql_db.one("SELECT COUNT(*) AS count FROM map_projects")["count"] == 1
    assert mysql_db.one("SELECT COUNT(*) AS count FROM map_project_sources")[
        "count"
    ] == 1

    with pytest.raises(MapProjectSourceValidationError):
        repository.save_public_map_draft(
            "another_project",
            _public_draft(
                profile_hash,
                {"physical_features_import": source["source_uuid"]},
            ),
            expected_revision=0,
            staged_sources=[],
        )
    assert mysql_db.one(
        "SELECT COUNT(*) AS count FROM map_projects WHERE map_name = 'another_project'"
    )["count"] == 0


def test_mysql_same_jsonl_two_projects_has_distinct_uuid_and_equal_hash(mysql_db):
    from fms_gateway.app.runtime_profiles import RuntimeProfileProvider

    repository = _repository()
    profile_hash = RuntimeProfileProvider(ROOT).load()["profile_hash"]
    waypoints, features = _public_records()
    stored = []
    for map_name in ("trihouse_test_01", "another_project"):
        source = _source(
            "physical_features_import",
            PHYSICAL_JSONL.read_bytes(),
            "application/x-ndjson",
            f"{map_name}.jsonl",
            metadata={"waypoints": waypoints, "features": features},
        )
        repository.save_public_map_draft(
            map_name,
            _public_draft(
                profile_hash,
                {"physical_features_import": source["source_uuid"]},
            ),
            expected_revision=0,
            staged_sources=[source],
        )
        stored.append(
            repository.get_map_project_source(map_name, source["source_uuid"])
        )
    assert stored[0]["source_uuid"] != stored[1]["source_uuid"]
    assert stored[0]["sha256"] == stored[1]["sha256"]


def test_mysql_active_delete_restores_manifest_draft_and_preserves_projection(
    mysql_db, tmp_path: Path
):
    from fms_gateway.app.map_deployment import MapDeploymentCoordinator
    from fms_gateway.app.runtime_profiles import RuntimeProfileProvider

    for code, name, location_type, temperature_zone in (
        ("WH-AMB-01", "Ambient Storage", "rack", "ambient"),
        ("WH-CHL-01", "Chilled Storage", "rack", "chilled"),
        ("WH-FRZ-01", "Frozen Storage", "rack", "frozen"),
        ("PACKING-01", "Packing Station", "workstation", "ambient"),
    ):
        mysql_db.execute(
            """
            INSERT INTO locations
              (location_code, name, location_type, temperature_zone)
            VALUES (%s, %s, %s, %s)
            """,
            (code, name, location_type, temperature_zone),
        )
    mysql_db.connection.commit()

    repository = _repository()
    profiles = RuntimeProfileProvider(ROOT)
    profile_hash = profiles.load()["profile_hash"]
    waypoints, features = _public_records()
    sources = [
        _source(
            "slam_yaml",
            (
                b"image: floor.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n"
                b"negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n"
            ),
            "application/x-yaml",
            "floor.yaml",
        ),
        _source(
            "slam_image",
            b"P5\n1 1\n255\n\x00",
            "image/x-portable-graymap",
            "floor.pgm",
        ),
        _source(
            "physical_features_import",
            PHYSICAL_JSONL.read_bytes(),
            "application/x-ndjson",
            "renamed-physical.data",
            metadata={"waypoints": waypoints, "features": features},
        ),
    ]
    source_uuids = {value["source_type"]: value["source_uuid"] for value in sources}
    saved = repository.save_public_map_draft(
        "trihouse_test_01",
        _public_draft(profile_hash, source_uuids),
        expected_revision=0,
        staged_sources=sources,
    )
    coordinator = MapDeploymentCoordinator(repository, tmp_path, profiles)
    staged = coordinator.stage("trihouse_test_01", saved["draft_revision"])
    assert coordinator.validate(staged) == ()
    published = coordinator.activate(staged, "W-OP-01")
    assert published["draft_revision"] == 1
    repeated_stage = coordinator.stage("trihouse_test_01", saved["draft_revision"])
    repeated = coordinator.activate(repeated_stage, "W-OP-01")
    assert repeated["map_revision"] == published["map_revision"]
    assert repeated["published_at"] == published["published_at"]
    assert mysql_db.one("SELECT COUNT(*) AS count FROM map_revisions")["count"] == 1
    active_pointer = json.loads(
        (tmp_path / "active" / "trihouse_test_01.json").read_text(
            encoding="utf-8"
        )
    )
    assert Path(active_pointer["manifest_path"]).is_file()
    assert not staged.staging_dir.exists()
    projected = repository.list_projected_map_features(published["map_revision"])
    assert len(projected) == 5
    fiducials = [value for value in projected if value["feature_type"] == "fiducial"]
    assert len(fiducials) == 3
    assert len(
        {
            tuple(value["geometry"]["coordinates"])
            for value in fiducials
        }
    ) == 3

    edited = repository.save_public_map_draft(
        "trihouse_test_01",
        _public_draft(
            profile_hash,
            source_uuids,
            extra_waypoints=[
                {
                    "code": "manual-after-publish",
                    "display_name": "Manual after publish",
                    "x": 9.0,
                    "y": 9.0,
                    "yaw": 0.0,
                    "origin": "manual",
                }
            ],
        ),
        expected_revision=1,
        staged_sources=[],
    )
    assert edited["draft_revision"] == 2
    repository.delete_public_map_draft("trihouse_test_01")

    restored = repository.get_public_map_draft("trihouse_test_01")
    assert restored["draft_revision"] == published["draft_revision"]
    assert all(
        value["code"] != "manual-after-publish" for value in restored["waypoints"]
    )
    assert repository.active_revision("trihouse_test_01") == published["map_revision"]
    assert mysql_db.one("SELECT COUNT(*) AS count FROM map_project_sources")[
        "count"
    ] == 3


def test_mysql_publish_fence_rejects_committed_save_after_validation(
    mysql_db, tmp_path: Path, monkeypatch
):
    from fms_gateway.app.map_deployment import MapDeploymentCoordinator
    from fms_gateway.app.runtime_profiles import RuntimeProfileProvider

    repository = _race_repository()
    profiles = RuntimeProfileProvider(ROOT)
    profile_hash = profiles.load()["profile_hash"]
    waypoints, features = _public_records()
    sources = [
        _source(
            "slam_yaml",
            (
                b"image: floor.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n"
                b"negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n"
            ),
            "application/x-yaml",
            "floor.yaml",
        ),
        _source(
            "slam_image",
            b"P5\n1 1\n255\n\x00",
            "image/x-portable-graymap",
            "floor.pgm",
        ),
        _source(
            "physical_features_import",
            PHYSICAL_JSONL.read_bytes(),
            "application/x-ndjson",
            "physical.jsonl",
            metadata={"waypoints": waypoints, "features": features},
        ),
    ]
    source_uuids = {source["source_type"]: source["source_uuid"] for source in sources}
    saved = repository.save_public_map_draft(
        "trihouse_test_01",
        _public_draft(profile_hash, source_uuids),
        expected_revision=0,
        staged_sources=sources,
    )
    coordinator = MapDeploymentCoordinator(repository, tmp_path, profiles)
    staged = coordinator.stage("trihouse_test_01", saved["draft_revision"])
    assert coordinator.validate(staged) == ()
    original_publish = repository.publish_map_project

    def save_then_publish(map_name: str, publication: dict):
        concurrent_repository = _race_repository()
        concurrent_repository.save_public_map_draft(
            map_name,
            _public_draft(
                profile_hash,
                source_uuids,
                extra_waypoints=[
                    {
                        "code": "manual-race",
                        "display_name": "Manual race",
                        "x": 9.0,
                        "y": 9.0,
                        "yaw": 0.0,
                        "origin": "manual",
                    }
                ],
            ),
            expected_revision=1,
            staged_sources=[],
        )
        return original_publish(map_name, publication)

    monkeypatch.setattr(repository, "publish_map_project", save_then_publish)

    with pytest.raises(MapDraftRevisionConflict):
        coordinator.activate(staged, "W-OP-01")
    assert mysql_db.one("SELECT draft_revision FROM map_projects")[
        "draft_revision"
    ] == 2
    assert mysql_db.one("SELECT COUNT(*) AS count FROM map_revisions")["count"] == 0
    assert not staged.staging_dir.exists()
