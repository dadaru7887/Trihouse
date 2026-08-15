"""Authoritative physical-feature JSONL import contract."""

from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[3]
PHYSICAL_JSONL = (
    ROOT
    / "control_ui"
    / "rmf_control_ui"
    / "data"
    / "import"
    / "trihouse_test_01_physical_features.jsonl"
)


def _importer():
    from fms_gateway.app.physical_features import PhysicalFeatureImporter

    return PhysicalFeatureImporter()


def _records() -> list[dict[str, object]]:
    return [json.loads(line) for line in PHYSICAL_JSONL.read_text(encoding="utf-8").splitlines()]


def _write_records(path: Path, records: list[dict[str, object]]) -> Path:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def test_physical_fixture_is_the_only_pose_source() -> None:
    result = _importer().parse(PHYSICAL_JSONL)

    assert result.map_name == "trihouse_test_01"
    assert len(result.waypoints) == 8
    assert len(result.bottlenecks) == 2
    assert len(result.fiducials) == 3
    assert result.bottlenecks[0].radius_m == 0.1
    assert result.bottlenecks[0].source_diameter_m == 0.2
    assert result.waypoint("WH-FRZ-01-DOCK-01").pose != result.marker(0).recognition_pose

    assert {
        waypoint.location_code: (waypoint.pose.x, waypoint.pose.y, waypoint.pose.yaw)
        for waypoint in result.waypoints
    } == {
        "WH-AMB-01-DOCK-01": (1.234, 0.743, 2.255),
        "WH-CHL-01-DOCK-01": (1.26, 0.193, -2.258),
        "WH-FRZ-01-DOCK-01": (1.201, -0.799, -1.408),
        "PACKING-01-DOCK-01": (0.351, -0.49, 0.231),
        "PACKING-01-DOCK-02": (0.351, -1.017, 0.231),
        "TRIHOUSE-TEST-01-SAFETY-01": (0.613, -1.249, 0.0),
        "TRIHOUSE-TEST-01-CHG-01": (0.065, 0.227, -0.005),
        "TRIHOUSE-TEST-01-CHG-02": (0.076, -0.013, 0.239),
    }
    assert {
        bottleneck.feature_code: (
            bottleneck.pose.x,
            bottleneck.pose.y,
            bottleneck.radius_m,
            bottleneck.source_diameter_m,
        )
        for bottleneck in result.bottlenecks
    } == {
        "TRIHOUSE-TEST-01-BOTTLENECK-01": (0.841, -0.111, 0.1, 0.2),
        "TRIHOUSE-TEST-01-BOTTLENECK-02": (0.367, -0.762, 0.1, 0.2),
    }
    assert {
        binding.marker_id: (
            binding.recognition_pose.x,
            binding.recognition_pose.y,
            binding.recognition_pose.yaw,
        )
        for binding in result.fiducials
    } == {
        2: (1.234, 0.743, 2.255),
        1: (1.26, 0.193, -2.258),
        0: (1.37, -0.233, 1.772),
    }


def test_import_is_independent_of_upload_filename_and_project_filename(tmp_path: Path) -> None:
    renamed_upload = tmp_path / "operator-selected-source.data"
    renamed_upload.write_bytes(PHYSICAL_JSONL.read_bytes())

    result = _importer().parse(renamed_upload)

    assert result.map_name == "trihouse_test_01"
    assert result.waypoint("TRIHOUSE-TEST-01-CHG-01").pose.x == 0.065

    bytes_result = _importer().parse(PHYSICAL_JSONL.read_bytes())
    assert bytes_result == result


def test_imported_features_are_immutable() -> None:
    result = _importer().parse(PHYSICAL_JSONL)

    with pytest.raises(FrozenInstanceError):
        result.waypoints[0].pose.x = 99.0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda rows: rows[1].__setitem__("location_code", rows[0]["location_code"]),
            "duplicate location_code",
        ),
        (
            lambda rows: rows[0]["map_pose"].__setitem__("x", float("nan")),  # type: ignore[index,union-attr]
            "finite",
        ),
        (
            lambda rows: rows[0].__setitem__("record_type", "invented_feature"),
            "unsupported record_type",
        ),
        (
            lambda rows: rows[8].__setitem__("radius_m", 0.2),
            "half of source_diameter_m",
        ),
    ],
)
def test_import_rejects_invalid_business_and_geometry_data(
    tmp_path: Path, mutate, message: str
) -> None:
    records = _records()
    mutate(records)
    invalid = _write_records(tmp_path / "invalid.jsonl", records)

    with pytest.raises(ValueError, match=message):
        _importer().parse(invalid)


def test_canonical_p0_import_rejects_incomplete_record_counts(tmp_path: Path) -> None:
    incomplete = _write_records(tmp_path / "incomplete.jsonl", _records()[:-1])

    with pytest.raises(ValueError, match="8 waypoints, 2 bottlenecks, and 3 fiducials"):
        _importer().parse(incomplete)


def test_import_rejects_records_from_multiple_target_maps(tmp_path: Path) -> None:
    records = _records()
    records[-1]["target_map_name"] = "another_map"
    mixed = _write_records(tmp_path / "mixed.jsonl", records)

    with pytest.raises(ValueError, match="one target_map_name"):
        _importer().parse(mixed)


def test_project_source_storage_is_immutable_and_project_scoped() -> None:
    from fms_gateway.app.repositories import InMemoryFmsRepository

    repository = InMemoryFmsRepository()
    project = {
        "format_version": 1,
        "payload": {"version": 1},
        "files": [],
        "fleet": None,
        "robots": [],
    }
    repository.save_map_project("source_project_a", project, None)
    repository.save_map_project("source_project_b", project, None)
    source = {
        "source_type": "physical_features_import",
        "file_name": "physical.jsonl",
        "mime_type": "application/x-ndjson",
        "content_bytes": b"same-content",
        "metadata": {"schema_version": 1},
    }

    first = repository.store_map_project_source("source_project_a", source)
    second = repository.store_map_project_source("source_project_b", source)

    assert first["source_uuid"] != second["source_uuid"]
    assert first["sha256"] == second["sha256"]
    first["content_bytes"] = b"caller-mutation"
    stored = repository.get_map_project_source(
        "source_project_a", first["source_uuid"]
    )
    assert stored is not None
    assert stored["content_bytes"] == b"same-content"


def test_project_source_view_is_frozen_and_type_constrained() -> None:
    from fms_gateway.app.models import MapProjectSourceView

    source = MapProjectSourceView(
        source_uuid="00000000-0000-0000-0000-000000000701",
        source_type="physical_features_import",
        file_name="physical.jsonl",
        mime_type="application/x-ndjson",
        sha256="a" * 64,
        byte_size=3,
        metadata={"schema_version": 1},
        created_at="2026-08-16T12:00:00+09:00",
    )

    with pytest.raises(ValidationError):
        source.file_name = "changed.jsonl"
    with pytest.raises(ValidationError):
        MapProjectSourceView(
            **{
                **source.model_dump(),
                "source_type": "unconstrained_source",
            }
        )
