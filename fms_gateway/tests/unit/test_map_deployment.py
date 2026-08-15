import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import threading

import pytest

from fms_gateway.app.map_deployment import (
    MapDeploymentCoordinator,
    MapSourceStaging,
    MapWorkflowError,
)
from fms_gateway.app.repositories import InMemoryFmsRepository, MapDraftRevisionConflict
from fms_gateway.app.runtime_profiles import RuntimeProfileProvider


ROOT = Path(__file__).resolve().parents[3]
PHYSICAL_JSONL = (
    ROOT
    / "control_ui"
    / "rmf_control_ui"
    / "data"
    / "import"
    / "trihouse_test_01_physical_features.jsonl"
)
VALID_SLAM_YAML = b"""image: floor.pgm
resolution: 0.05
origin: [0.0, 0.0, 0.0]
negate: 0
occupied_thresh: 0.65
free_thresh: 0.196
"""
VALID_SLAM_IMAGE = b"P5\n1 1\n255\n\x00"


def _seed_parent_locations() -> list[dict]:
    return [
        {
            "location_id": index,
            "location_code": code,
            "name": code,
            "location_type": kind,
            "map_name": None,
            "metadata": {},
        }
        for index, (code, kind) in enumerate(
            (
                ("WH-AMB-01", "rack"),
                ("WH-CHL-01", "rack"),
                ("WH-FRZ-01", "rack"),
                ("PACKING-01", "workstation"),
            ),
            start=1,
        )
    ]


def _repository() -> InMemoryFmsRepository:
    try:
        return InMemoryFmsRepository(seed_locations=_seed_parent_locations())
    except TypeError:
        return InMemoryFmsRepository()


def _physical_public_records() -> tuple[list[dict], list[dict]]:
    from fms_gateway.app.map_deployment import physical_import_to_public_records
    from fms_gateway.app.physical_features import PhysicalFeatureImporter

    imported = PhysicalFeatureImporter().parse(PHYSICAL_JSONL.read_bytes())
    return physical_import_to_public_records(imported)


def _saved_public_project(repository: InMemoryFmsRepository, profile_hash: str) -> dict:
    waypoints, features = _physical_public_records()
    source_uuid = "11111111-1111-4111-8111-111111111111"
    source = {
        "source_uuid": source_uuid,
        "source_type": "physical_features_import",
        "file_name": "physical.jsonl",
        "mime_type": "application/x-ndjson",
        "content_bytes": PHYSICAL_JSONL.read_bytes(),
        "metadata": {"waypoints": waypoints, "features": features},
    }
    repository.save_public_map_draft(
        "trihouse_test_01",
        {
            "format_version": 1,
            "source_uuids": {"physical_features_import": source_uuid},
            "waypoints": waypoints,
            "features": features,
            "runtime_profile_hash": profile_hash,
        },
        expected_revision=0,
        staged_sources=[source],
    )
    return repository.get_public_map_draft("trihouse_test_01")


def _saved_deployable_project(
    repository: InMemoryFmsRepository,
    profile_hash: str,
    *,
    map_name: str = "trihouse_test_01",
) -> dict:
    waypoints, features = _physical_public_records()
    sources = [
        {
            "source_uuid": "11111111-1111-4111-8111-111111111111",
            "source_type": "slam_yaml",
            "file_name": "floor.yaml",
            "mime_type": "application/x-yaml",
            "content_bytes": VALID_SLAM_YAML,
            "metadata": None,
        },
        {
            "source_uuid": "22222222-2222-4222-8222-222222222222",
            "source_type": "slam_image",
            "file_name": "floor.pgm",
            "mime_type": "image/x-portable-graymap",
            "content_bytes": VALID_SLAM_IMAGE,
            "metadata": None,
        },
        {
            "source_uuid": "33333333-3333-4333-8333-333333333333",
            "source_type": "physical_features_import",
            "file_name": "physical.jsonl",
            "mime_type": "application/x-ndjson",
            "content_bytes": PHYSICAL_JSONL.read_bytes(),
            "metadata": {"waypoints": waypoints, "features": features},
        },
    ]
    repository.save_public_map_draft(
        map_name,
        {
            "format_version": 1,
            "source_uuids": {
                source["source_type"]: source["source_uuid"] for source in sources
            },
            "waypoints": waypoints,
            "features": features,
            "runtime_profile_hash": profile_hash,
        },
        expected_revision=0,
        staged_sources=sources,
    )
    return repository.get_public_map_draft(map_name)


def _rewrite_manifest(staged, mutate) -> None:
    manifest = json.loads(staged.manifest_path.read_text(encoding="utf-8"))
    mutate(manifest)
    staged.manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def test_runtime_profile_reads_pinned_files_and_hashes_their_bytes():
    profile = RuntimeProfileProvider(repository_root=ROOT).load()

    assert profile["profile_name"] == "pinky_pro simulation profile"
    assert profile["source_files"] == [
        "pinky_pro/pinky_navigation/params/nav2_params.yaml",
        "pinky_pro/pinky_bringup/config/pinky_params.yaml",
    ]
    assert profile["controller"]["plugin"] == (
        "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController"
    )
    assert profile["planner"]["plugin"] == "nav2_navfn_planner::NavfnPlanner"
    assert profile["local_costmap"]["resolution"] == 0.05
    assert profile["global_costmap"]["resolution"] == 0.05
    assert profile["robot"]["footprint"] == [
        [0.06, 0.06],
        [0.06, -0.06],
        [-0.06, -0.06],
        [-0.06, 0.06],
    ]
    assert profile["robot"]["dimensions_m"] == {"length": 0.12, "width": 0.12}
    assert profile["robot"]["robot_radius_m"] is None
    assert profile["max_speeds"] == {"linear_mps": 0.25, "angular_radps": 1.5}
    assert profile["goal_tolerances"] == {"xy_m": 0.25, "yaw_rad": 0.25}
    assert profile["progress_tolerances"] == {
        "required_movement_radius_m": 0.5,
        "movement_time_allowance_s": 10.0,
    }
    assert profile["wheel_parameters"] == {
        "wheel_radius_m": 0.027,
        "wheel_separation_m": 0.0961,
    }
    source_hashes = [
        hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in profile["source_files"]
    ]
    expected_hash = hashlib.sha256(
        json.dumps(
            list(zip(profile["source_files"], source_hashes, strict=True)),
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert profile["profile_hash"] == expected_hash


def test_stage_is_filesystem_only_and_validation_returns_immutable_codes(
    tmp_path: Path,
):
    repository = _repository()
    profiles = RuntimeProfileProvider(repository_root=ROOT)
    draft = _saved_public_project(repository, profiles.load()["profile_hash"])
    coordinator = MapDeploymentCoordinator(repository, tmp_path, profiles)

    staged = coordinator.stage("trihouse_test_01", draft["draft_revision"])

    assert staged.manifest_path.is_file()
    assert repository.active_revision("trihouse_test_01") is None
    errors = coordinator.validate(staged)
    assert isinstance(errors, tuple)
    assert errors == ("SOURCE_SLAM_IMAGE_MISSING", "SOURCE_SLAM_YAML_MISSING")
    assert repository.deployment_failure_events("trihouse_test_01") == []


def test_validation_failure_does_not_replace_active_or_add_failure_audit(
    tmp_path: Path,
):
    repository = _repository()
    profiles = RuntimeProfileProvider(repository_root=ROOT)
    draft = _saved_public_project(repository, profiles.load()["profile_hash"])
    coordinator = MapDeploymentCoordinator(repository, tmp_path, profiles)

    invalid = coordinator.stage("trihouse_test_01", draft["draft_revision"])
    assert coordinator.validate(invalid)
    assert repository.active_revision("trihouse_test_01") is None
    assert repository.deployment_failure_events("trihouse_test_01") == []


def test_reconcile_removes_orphan_stage_without_creating_revision(tmp_path: Path):
    repository = _repository()
    profiles = RuntimeProfileProvider(repository_root=ROOT)
    draft = _saved_public_project(repository, profiles.load()["profile_hash"])
    coordinator = MapDeploymentCoordinator(repository, tmp_path, profiles)
    staged = coordinator.stage("trihouse_test_01", draft["draft_revision"])

    reconciled = coordinator.reconcile_startup()

    assert reconciled == (staged.deployment_uuid,)
    assert not staged.staging_dir.exists()
    assert repository.active_revision("trihouse_test_01") is None


def test_validation_rehashes_manifest_snapshot_and_binds_all_snapshot_fields(
    tmp_path: Path,
):
    repository = _repository()
    profiles = RuntimeProfileProvider(repository_root=ROOT)
    draft = _saved_deployable_project(repository, profiles.load()["profile_hash"])
    coordinator = MapDeploymentCoordinator(repository, tmp_path, profiles)
    staged = coordinator.stage("trihouse_test_01", draft["draft_revision"])

    def tamper(manifest: dict) -> None:
        manifest["draft_snapshot"]["waypoints"][0]["x"] = 999.0
        manifest["draft_snapshot"]["source_uuids"] = {}
        manifest["draft_snapshot"]["runtime_profile_hash"] = "0" * 64

    _rewrite_manifest(staged, tamper)

    assert {
        "DEPLOYMENT_SNAPSHOT_HASH_MISMATCH",
        "DEPLOYMENT_SOURCE_MANIFEST_MISMATCH",
        "DEPLOYMENT_PROFILE_BINDING_MISMATCH",
    }.issubset(coordinator.validate(staged))


def test_validation_rehashes_persisted_source_bytes_not_metadata_columns(
    tmp_path: Path,
):
    repository = _repository()
    profiles = RuntimeProfileProvider(repository_root=ROOT)
    draft = _saved_deployable_project(repository, profiles.load()["profile_hash"])
    coordinator = MapDeploymentCoordinator(repository, tmp_path, profiles)
    staged = coordinator.stage("trihouse_test_01", draft["draft_revision"])
    image_uuid = draft["source_uuids"]["slam_image"]
    repository._map_project_sources["trihouse_test_01"][image_uuid][
        "content_bytes"
    ] = b"P5\n2 1\n255\n\x00\x00"

    assert "SOURCE_HASH_MISMATCH" in coordinator.validate(staged)


@pytest.mark.parametrize(
    ("source_type", "content", "expected_code"),
    [
        (
            "slam_yaml",
            b"image: other.pgm\nresolution: .inf\norigin: [0, 0, 0]\n",
            "SLAM_YAML_INVALID",
        ),
        ("slam_image", b"P5\n2 nope\n255\n", "SLAM_IMAGE_INVALID"),
    ],
)
def test_validation_preflights_slam_yaml_contract_and_image_shape(
    tmp_path: Path,
    source_type: str,
    content: bytes,
    expected_code: str,
):
    repository = _repository()
    profiles = RuntimeProfileProvider(repository_root=ROOT)
    draft = _saved_deployable_project(repository, profiles.load()["profile_hash"])
    coordinator = MapDeploymentCoordinator(repository, tmp_path, profiles)
    source_uuid = draft["source_uuids"][source_type]
    stored = repository._map_project_sources["trihouse_test_01"][source_uuid]
    stored["content_bytes"] = content
    stored["sha256"] = hashlib.sha256(content).hexdigest()
    stored["byte_size"] = len(content)
    staged = coordinator.stage("trihouse_test_01", draft["draft_revision"])

    assert expected_code in coordinator.validate(staged)


def test_validation_rejects_png_header_without_decodable_pixel_data(tmp_path: Path):
    repository = _repository()
    profiles = RuntimeProfileProvider(repository_root=ROOT)
    draft = _saved_deployable_project(repository, profiles.load()["profile_hash"])
    image_uuid = draft["source_uuids"]["slam_image"]
    yaml_uuid = draft["source_uuids"]["slam_yaml"]
    image = repository._map_project_sources["trihouse_test_01"][image_uuid]
    yaml_source = repository._map_project_sources["trihouse_test_01"][yaml_uuid]
    header_only = (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
        + b"\x00\x00\x00\x00"
    )
    image.update(
        {
            "file_name": "floor.png",
            "mime_type": "image/png",
            "content_bytes": header_only,
            "sha256": hashlib.sha256(header_only).hexdigest(),
            "byte_size": len(header_only),
        }
    )
    yaml_content = VALID_SLAM_YAML.replace(b"floor.pgm", b"floor.png")
    yaml_source.update(
        {
            "content_bytes": yaml_content,
            "sha256": hashlib.sha256(yaml_content).hexdigest(),
            "byte_size": len(yaml_content),
        }
    )
    coordinator = MapDeploymentCoordinator(repository, tmp_path, profiles)
    staged = coordinator.stage("trihouse_test_01", draft["draft_revision"])

    assert "SLAM_IMAGE_INVALID" in coordinator.validate(staged)


def test_validation_requires_exact_reproducible_artifact_set(tmp_path: Path):
    repository = _repository()
    profiles = RuntimeProfileProvider(repository_root=ROOT)
    draft = _saved_deployable_project(repository, profiles.load()["profile_hash"])
    coordinator = MapDeploymentCoordinator(repository, tmp_path, profiles)
    staged = coordinator.stage("trihouse_test_01", draft["draft_revision"])

    def tamper(manifest: dict) -> None:
        manifest["artifacts"].pop("world_sdf")
        manifest["artifacts"]["unexpected"] = {
            "content": "surprise",
            "sha256": hashlib.sha256(b"surprise").hexdigest(),
        }
        altered = "name: attacker-controlled\n"
        manifest["artifacts"]["building_yaml"] = {
            "content": altered,
            "sha256": hashlib.sha256(altered.encode()).hexdigest(),
        }

    _rewrite_manifest(staged, tamper)

    errors = coordinator.validate(staged)
    assert "RUNTIME_ARTIFACT_SET_INVALID" in errors
    assert "RUNTIME_ARTIFACT_CONTENT_MISMATCH" in errors


def test_physical_fixture_can_be_reused_by_a_differently_named_project(
    tmp_path: Path,
):
    repository = _repository()
    profiles = RuntimeProfileProvider(repository_root=ROOT)
    draft = _saved_deployable_project(
        repository,
        profiles.load()["profile_hash"],
        map_name="another_project",
    )
    coordinator = MapDeploymentCoordinator(repository, tmp_path, profiles)

    staged = coordinator.stage("another_project", draft["draft_revision"])

    assert coordinator.validate(staged) == ()


def test_activation_fence_rejects_save_after_validate_and_cleans_stage(
    tmp_path: Path,
):
    repository = _repository()
    profiles = RuntimeProfileProvider(repository_root=ROOT)
    draft = _saved_deployable_project(repository, profiles.load()["profile_hash"])
    coordinator = MapDeploymentCoordinator(repository, tmp_path, profiles)
    staged = coordinator.stage("trihouse_test_01", draft["draft_revision"])
    original_publish = repository.publish_map_project

    def save_then_publish(map_name: str, publication: dict):
        current = repository.get_public_map_draft(map_name)
        repository.save_public_map_draft(
            map_name,
            {
                **current,
                "waypoints": current["waypoints"]
                + [
                    {
                        "code": "manual-race",
                        "display_name": "Manual race",
                        "x": 9.0,
                        "y": 9.0,
                        "yaw": 0.0,
                        "origin": "manual",
                    }
                ],
            },
            expected_revision=current["draft_revision"],
            staged_sources=[],
        )
        return original_publish(map_name, publication)

    repository.publish_map_project = save_then_publish  # type: ignore[method-assign]

    with pytest.raises(MapDraftRevisionConflict):
        coordinator.activate(staged, "W-OP-01")
    assert repository.active_revision("trihouse_test_01") is None
    assert not staged.staging_dir.exists()


def test_repeated_unchanged_publish_is_idempotent_and_does_not_leak_stage(
    tmp_path: Path,
):
    repository = _repository()
    profiles = RuntimeProfileProvider(repository_root=ROOT)
    draft = _saved_deployable_project(repository, profiles.load()["profile_hash"])
    coordinator = MapDeploymentCoordinator(repository, tmp_path, profiles)

    first_stage = coordinator.stage("trihouse_test_01", draft["draft_revision"])
    first = coordinator.activate(first_stage, "W-OP-01")
    second_stage = coordinator.stage("trihouse_test_01", draft["draft_revision"])
    second = coordinator.activate(second_stage, "W-OP-01")

    assert second["map_revision"] == first["map_revision"]
    assert second["published_at"] == first["published_at"]
    assert not second_stage.staging_dir.exists()


def test_active_manifest_and_pointer_are_fsynced_in_safe_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repository = _repository()
    profiles = RuntimeProfileProvider(repository_root=ROOT)
    draft = _saved_deployable_project(repository, profiles.load()["profile_hash"])
    coordinator = MapDeploymentCoordinator(repository, tmp_path, profiles)
    staged = coordinator.stage("trihouse_test_01", draft["draft_revision"])
    events: list[str] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def fsync_spy(fd: int) -> None:
        events.append("fsync-dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync-file")
        real_fsync(fd)

    def replace_spy(source, destination) -> None:
        events.append(f"replace-{Path(destination).name}")
        real_replace(source, destination)

    monkeypatch.setattr("fms_gateway.app.map_deployment.os.fsync", fsync_spy)
    monkeypatch.setattr("fms_gateway.app.map_deployment.os.replace", replace_spy)

    coordinator.activate(staged, "W-OP-01")

    manifest_replace = events.index("replace-manifest.json")
    pointer_replace = events.index("replace-trihouse_test_01.json")
    assert events[manifest_replace - 1] == "fsync-file"
    assert events[manifest_replace + 1] == "fsync-dir"
    assert events[pointer_replace - 1] == "fsync-file"
    assert events[pointer_replace + 1] == "fsync-dir"
    assert manifest_replace < pointer_replace


def test_concurrent_source_claim_loser_gets_stable_consumed_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    staging = MapSourceStaging(tmp_path)
    source = staging.stage(
        "trihouse_test_01",
        "slam_yaml",
        "floor.yaml",
        "application/x-yaml",
        VALID_SLAM_YAML,
    )
    barrier = threading.Barrier(2)
    original = staging._source_from_dir

    def synchronized_read(directory: Path):
        result = original(directory)
        if directory.parent == staging.pending_root:
            barrier.wait(timeout=3)
        return result

    monkeypatch.setattr(staging, "_source_from_dir", synchronized_read)
    outcomes: list[object] = []

    def claim() -> None:
        try:
            outcomes.append(staging.claim_many("trihouse_test_01", {"slam_yaml": source.upload_token}))
        except Exception as error:
            outcomes.append(error)

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    errors = [value for value in outcomes if isinstance(value, MapWorkflowError)]
    winners = [value for value in outcomes if isinstance(value, tuple)]
    assert len(winners) == 1
    assert [error.code for error in errors] == ["STAGED_SOURCE_TOKEN_CONSUMED"]
