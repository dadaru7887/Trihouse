import hashlib
import json
from pathlib import Path

from fms_gateway.app.map_deployment import MapDeploymentCoordinator
from fms_gateway.app.repositories import InMemoryFmsRepository
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
    repository = InMemoryFmsRepository()
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
    repository = InMemoryFmsRepository()
    profiles = RuntimeProfileProvider(repository_root=ROOT)
    draft = _saved_public_project(repository, profiles.load()["profile_hash"])
    coordinator = MapDeploymentCoordinator(repository, tmp_path, profiles)

    invalid = coordinator.stage("trihouse_test_01", draft["draft_revision"])
    assert coordinator.validate(invalid)
    assert repository.active_revision("trihouse_test_01") is None
    assert repository.deployment_failure_events("trihouse_test_01") == []


def test_reconcile_removes_orphan_stage_without_creating_revision(tmp_path: Path):
    repository = InMemoryFmsRepository()
    profiles = RuntimeProfileProvider(repository_root=ROOT)
    draft = _saved_public_project(repository, profiles.load()["profile_hash"])
    coordinator = MapDeploymentCoordinator(repository, tmp_path, profiles)
    staged = coordinator.stage("trihouse_test_01", draft["draft_revision"])

    reconciled = coordinator.reconcile_startup()

    assert reconciled == (staged.deployment_uuid,)
    assert not staged.staging_dir.exists()
    assert repository.active_revision("trihouse_test_01") is None
