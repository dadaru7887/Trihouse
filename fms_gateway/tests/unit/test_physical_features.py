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


def _duplicate_first_record_fragment(fragment: str, replacement: str) -> bytes:
    lines = PHYSICAL_JSONL.read_text(encoding="utf-8").splitlines()
    assert fragment in lines[0]
    lines[0] = lines[0].replace(fragment, replacement, 1)
    return ("\n".join(lines) + "\n").encode()


def _cyclic_metadata() -> dict[str, object]:
    metadata: dict[str, object] = {}
    metadata["cycle"] = metadata
    return metadata


def test_physical_fixture_is_the_only_pose_source() -> None:
    from fms_gateway.app.physical_features import MapPose

    records = _records()
    result = _importer().parse(PHYSICAL_JSONL)

    assert result.map_name == "trihouse_test_01"
    assert len(result.waypoints) == 8
    assert len(result.bottlenecks) == 2
    assert len(result.fiducials) == 3
    assert all(feature.radius_m == 0.1 for feature in result.bottlenecks)
    assert all(feature.source_diameter_m == 0.2 for feature in result.bottlenecks)
    assert all(
        feature.radius_m == feature.source_diameter_m / 2
        for feature in result.bottlenecks
    )
    assert {binding.target_location_code for binding in result.fiducials} == {
        "WH-AMB-01-DOCK-01",
        "WH-CHL-01-DOCK-01",
        "WH-FRZ-01-DOCK-01",
    }
    assert result.waypoint("WH-FRZ-01-DOCK-01").pose != result.marker(0).recognition_pose

    for record in records:
        if record["record_type"] == "waypoint":
            assert result.waypoint(record["location_code"]).pose == MapPose(
                **record["map_pose"]
            )
        elif record["record_type"] == "bottleneck":
            imported = next(
                feature
                for feature in result.bottlenecks
                if feature.feature_code == record["feature_code"]
            )
            assert imported.pose == MapPose(**record["map_pose"])
            assert imported.radius_m == record["radius_m"]
            assert imported.source_diameter_m == record["source_diameter_m"]
        else:
            assert result.marker(record["marker_id"]).recognition_pose == MapPose(
                **record["recognition_pose"]
            )


def test_import_is_independent_of_upload_filename_and_project_filename(tmp_path: Path) -> None:
    renamed_upload = tmp_path / "operator-selected-source.data"
    renamed_upload.write_bytes(PHYSICAL_JSONL.read_bytes())

    result = _importer().parse(renamed_upload)

    assert result.map_name == "trihouse_test_01"
    raw_charger = next(
        record
        for record in _records()
        if record.get("location_code") == "TRIHOUSE-TEST-01-CHG-01"
    )
    assert result.waypoint("TRIHOUSE-TEST-01-CHG-01").pose.x == raw_charger[
        "map_pose"
    ]["x"]

    bytes_result = _importer().parse(PHYSICAL_JSONL.read_bytes())
    assert bytes_result == result


def test_imported_features_are_immutable() -> None:
    result = _importer().parse(PHYSICAL_JSONL)

    with pytest.raises(FrozenInstanceError):
        result.waypoints[0].pose.x = 99.0  # type: ignore[misc]


def test_import_rejects_duplicate_top_level_json_names() -> None:
    from fms_gateway.app.physical_features import PhysicalFeatureImportError

    record = _records()[0]
    value = json.dumps(record["source_id"], ensure_ascii=False)
    field = f'"source_id":{value}'
    duplicate = f'{field},"source_id":{value}'

    with pytest.raises(
        PhysicalFeatureImportError,
        match=r"line 1:.*duplicate JSON key.*source_id",
    ):
        _importer().parse(_duplicate_first_record_fragment(field, duplicate))


@pytest.mark.parametrize(
    ("container", "field_name", "expected_path"),
    [
        ("map_pose", "x", r"map_pose\.x"),
        (
            "source_measurements",
            "timestamp",
            r"source_measurements\[0\]\.timestamp",
        ),
    ],
)
def test_import_rejects_duplicate_nested_json_names(
    container: str, field_name: str, expected_path: str
) -> None:
    from fms_gateway.app.physical_features import PhysicalFeatureImportError

    record = _records()[0]
    if container == "map_pose":
        nested = record[container]
    else:
        nested = record[container][0]
    value = json.dumps(nested[field_name], ensure_ascii=False)
    prefix = f'"{container}":' + ("[{" if container == "source_measurements" else "{")
    field = f'{prefix}"{field_name}":{value}'
    duplicate = f'{field},"{field_name}":{value}'

    with pytest.raises(
        PhysicalFeatureImportError,
        match=rf"line 1:.*duplicate JSON key.*{expected_path}",
    ):
        _importer().parse(_duplicate_first_record_fragment(field, duplicate))


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


@pytest.mark.parametrize(
    ("mutate", "field"),
    [
        (lambda rows: rows[0].__setitem__("schema_version", True), "schema_version"),
        (lambda rows: rows[0].pop("source_map_name"), "source_map_name"),
        (lambda rows: rows[0].pop("source_labels"), "source_labels"),
        (lambda rows: rows[0].pop("source_measurements"), "source_measurements"),
        (lambda rows: rows[0].pop("yaw_source"), "yaw_source"),
        (lambda rows: rows[0].__setitem__("source_id", " padded"), "source_id"),
        (
            lambda rows: rows[0].__setitem__("parent_location_code", "WH AMB 01"),
            "parent_location_code",
        ),
        (
            lambda rows: rows[0].__setitem__(
                "target_map_name", rows[0]["target_map_name"] + " "
            ),
            "target_map_name",
        ),
        (lambda rows: rows[0].__setitem__("radius_m", 0.1), "radius_m"),
        (lambda rows: rows[0].__setitem__("invented", "field"), "invented"),
    ],
)
def test_import_rejects_incomplete_mixed_or_noncanonical_record_schema(
    tmp_path: Path, mutate, field: str
) -> None:
    from fms_gateway.app.physical_features import PhysicalFeatureImportError

    records = _records()
    mutate(records)

    with pytest.raises(PhysicalFeatureImportError, match=rf"line 1:.*{field}"):
        _importer().parse(_write_records(tmp_path / "invalid-schema.jsonl", records))


def test_import_rejects_cross_type_business_code_duplicates(tmp_path: Path) -> None:
    from fms_gateway.app.physical_features import PhysicalFeatureImportError

    records = _records()
    records[8]["feature_code"] = records[0]["location_code"]

    with pytest.raises(
        PhysicalFeatureImportError,
        match=r"line 9:.*duplicate feature_code",
    ):
        _importer().parse(_write_records(tmp_path / "duplicate-code.jsonl", records))


@pytest.mark.parametrize(
    "replacement",
    [
        lambda rows: rows[10]["target_location_code"],
        lambda rows: rows[3]["location_code"],
    ],
)
def test_canonical_import_requires_one_binding_for_each_warehouse_dock(
    tmp_path: Path, replacement
) -> None:
    from fms_gateway.app.physical_features import PhysicalFeatureImportError

    records = _records()
    records[12]["target_location_code"] = replacement(records)

    with pytest.raises(PhysicalFeatureImportError, match="fiducial.*target_location_code"):
        _importer().parse(_write_records(tmp_path / "duplicate-binding.jsonl", records))


@pytest.mark.parametrize(
    ("mutate", "field"),
    [
        (lambda rows: rows[0].__setitem__("source_measurements", None), "source_measurements"),
        (lambda rows: rows[0].__setitem__("source_measurements", []), "source_measurements"),
        (
            lambda rows: rows[0]["source_measurements"][0].pop("timestamp"),
            r"source_measurements\[0\]\.timestamp",
        ),
        (
            lambda rows: rows[0]["source_measurements"][0].__setitem__(
                "unknown", "field"
            ),
            r"source_measurements\[0\]\.unknown",
        ),
        (
            lambda rows: rows[0]["source_measurements"][0].__setitem__("map_x", "1"),
            r"source_measurements\[0\]\.map_x",
        ),
        (
            lambda rows: rows[0]["source_measurements"][0].__setitem__("note", None),
            r"source_measurements\[0\]\.note",
        ),
    ],
)
def test_import_rejects_malformed_source_measurements(
    tmp_path: Path, mutate, field: str
) -> None:
    from fms_gateway.app.physical_features import PhysicalFeatureImportError

    records = _records()
    mutate(records)

    with pytest.raises(PhysicalFeatureImportError, match=rf"line 1:.*{field}"):
        _importer().parse(_write_records(tmp_path / "bad-measurement.jsonl", records))


@pytest.mark.parametrize(
    ("mutate", "line_number"),
    [
        (
            lambda rows: rows[0]["source_measurements"][0].__setitem__(
                "map_x", rows[0]["map_pose"]["x"] + 1
            ),
            1,
        ),
        (
            lambda rows: rows[8]["source_measurements"][0].__setitem__(
                "source_diameter_m", rows[8]["source_diameter_m"] + 1
            ),
            9,
        ),
        (
            lambda rows: rows[10]["source_measurements"][0].__setitem__(
                "marker_id", rows[10]["marker_id"] + 1
            ),
            11,
        ),
    ],
)
def test_source_measurements_must_support_selected_record_values(
    tmp_path: Path, mutate, line_number: int
) -> None:
    from fms_gateway.app.physical_features import PhysicalFeatureImportError

    records = _records()
    mutate(records)

    with pytest.raises(
        PhysicalFeatureImportError,
        match=rf"line {line_number}: source_measurements",
    ):
        _importer().parse(_write_records(tmp_path / "inconsistent-source.jsonl", records))


@pytest.mark.parametrize(
    "bad_value",
    [True, "1.0", None, float("inf"), float("nan"), 10**400],
)
def test_numeric_failures_are_contextual_import_errors(
    tmp_path: Path, bad_value: object
) -> None:
    from fms_gateway.app.physical_features import PhysicalFeatureImportError

    records = _records()
    records[0]["map_pose"]["x"] = bad_value

    with pytest.raises(
        PhysicalFeatureImportError,
        match=r"line 1: map_pose\.x must be a finite number",
    ):
        _importer().parse(_write_records(tmp_path / "bad-number.jsonl", records))


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
    first["content_bytes"] = b"caller-mutation"
    first["metadata"]["nested"]["value"] = "caller-mutation"
    stored = repository.get_map_project_source(
        "source_project_a", first["source_uuid"]
    )
    assert stored is not None
    assert stored["content_bytes"] == b"same-content"
    assert stored["metadata"]["nested"]["value"] == "original"
    assert (
        repository.get_map_project_source("source_project_b", first["source_uuid"])
        is None
    )

    repository.delete_map_project("source_project_a")
    repository.save_map_project("source_project_a", project, None)
    assert (
        repository.get_map_project_source("source_project_a", first["source_uuid"])
        is None
    )


@pytest.mark.parametrize(
    "metadata_factory",
    [
        lambda: {"bad": object()},
        lambda: {"bad": float("nan")},
        lambda: {1: "non-string-key"},
        _cyclic_metadata,
    ],
)
def test_in_memory_source_metadata_rejects_non_json_values(metadata_factory) -> None:
    from fms_gateway.app.repositories import (
        InMemoryFmsRepository,
        MapProjectSourceValidationError,
    )

    repository = InMemoryFmsRepository()
    repository.save_map_project(
        "source_project",
        {
            "format_version": 1,
            "payload": {"version": 1},
            "files": [],
            "fleet": None,
            "robots": [],
        },
        None,
    )

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


def _in_memory_repository_for_source_metadata():
    from fms_gateway.app.repositories import InMemoryFmsRepository

    repository = InMemoryFmsRepository()
    repository.save_map_project(
        "source_project",
        {
            "format_version": 1,
            "payload": {"version": 1},
            "files": [],
            "fleet": None,
            "robots": [],
        },
        None,
    )
    return repository


def _source_with_metadata(metadata: dict[str, object]) -> dict[str, object]:
    return {
        "source_type": "physical_features_import",
        "file_name": "physical.jsonl",
        "mime_type": "application/x-ndjson",
        "content_bytes": b"content",
        "metadata": metadata,
    }


@pytest.mark.parametrize("value", [-(2**53 - 1), 2**53 - 1])
def test_in_memory_source_metadata_round_trips_safe_integer_boundaries(
    value: int,
) -> None:
    repository = _in_memory_repository_for_source_metadata()

    stored = repository.store_map_project_source(
        "source_project",
        _source_with_metadata({"nested": {"value": value}, "enabled": True}),
    )
    loaded = repository.get_map_project_source(
        "source_project", stored["source_uuid"]
    )

    assert loaded is not None
    assert loaded["metadata"]["nested"]["value"] == value
    assert type(loaded["metadata"]["nested"]["value"]) is int
    assert loaded["metadata"]["enabled"] is True


@pytest.mark.parametrize("value", [-(2**53), 2**53, 10**400])
def test_in_memory_source_metadata_rejects_integers_outside_safe_range(
    value: int,
) -> None:
    from fms_gateway.app.repositories import MapProjectSourceValidationError

    repository = _in_memory_repository_for_source_metadata()

    with pytest.raises(
        MapProjectSourceValidationError,
        match=r"metadata \$\.nested\.value.*safe integer",
    ):
        repository.store_map_project_source(
            "source_project",
            _source_with_metadata({"nested": {"value": value}}),
        )


def test_project_source_view_is_frozen_and_type_constrained() -> None:
    from fms_gateway.app.models import MapProjectSourceView

    input_metadata = {"nested": {"value": 1}, "items": [1, 2]}
    source = MapProjectSourceView(
        source_uuid="00000000-0000-0000-0000-000000000701",
        source_type="physical_features_import",
        file_name="physical.jsonl",
        mime_type="application/x-ndjson",
        sha256="a" * 64,
        byte_size=3,
        metadata=input_metadata,
        created_at="2026-08-16T12:00:00+09:00",
    )

    with pytest.raises(ValidationError):
        source.file_name = "changed.jsonl"
    input_metadata["nested"]["value"] = 2
    assert source.metadata is not None
    assert source.metadata["nested"]["value"] == 1
    with pytest.raises(TypeError):
        source.metadata["nested"]["value"] = 3
    with pytest.raises(TypeError):
        source.metadata["items"][0] = 3
    assert source.model_dump()["metadata"] == {
        "nested": {"value": 1},
        "items": [1, 2],
    }
    with pytest.raises(ValidationError):
        MapProjectSourceView(
            **{
                **source.model_dump(),
                "source_type": "unconstrained_source",
            }
        )
