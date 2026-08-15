"""Strict import of authoritative physical-feature JSONL records."""

from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import re
from typing import Any


CANONICAL_P0_MAP_NAME = "trihouse_test_01"
CANONICAL_P0_COUNTS = (8, 2, 3)
CANONICAL_P0_FIDUCIAL_TARGETS = frozenset(
    {
        "WH-AMB-01-DOCK-01",
        "WH-CHL-01-DOCK-01",
        "WH-FRZ-01-DOCK-01",
    }
)
MAP_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,94}$")

COMMON_FIELDS = frozenset(
    {
        "schema_version",
        "record_type",
        "source_id",
        "target_map_name",
        "source_map_name",
        "source_labels",
        "source_measurements",
    }
)
WAYPOINT_FIELDS = COMMON_FIELDS | {
    "display_name",
    "rmf_waypoint_name",
    "location_code",
    "operational_role",
    "parent_location_code",
    "temperature_zone",
    "map_pose",
    "yaw_source",
    "departure_pose",
}
BOTTLENECK_FIELDS = COMMON_FIELDS | {
    "display_name",
    "feature_code",
    "mutex_group",
    "map_pose",
    "radius_m",
    "source_diameter_m",
}
FIDUCIAL_FIELDS = COMMON_FIELDS | {
    "marker_id",
    "dictionary",
    "target_location_code",
    "recognition_pose",
    "pixel_size",
}

MEASUREMENT_COMMON_FIELDS = {
    "timestamp",
    "label",
    "note",
    "map_x",
    "map_y",
    "amcl_xy_stddev_m",
}
WAYPOINT_MEASUREMENT_FIELDS = MEASUREMENT_COMMON_FIELDS | {"map_yaw"}
BOTTLENECK_MEASUREMENT_FIELDS = MEASUREMENT_COMMON_FIELDS | {"source_diameter_m"}
FIDUCIAL_MEASUREMENT_FIELDS = MEASUREMENT_COMMON_FIELDS | {
    "marker_id",
    "dict",
    "pixel_size",
    "map_yaw",
}


class PhysicalFeatureImportError(ValueError):
    """Raised when a physical-feature JSONL source violates its data contract."""


@dataclass(frozen=True)
class _JsonObjectPairs:
    pairs: tuple[tuple[str, Any], ...]


class _DuplicateJsonKey(ValueError):
    def __init__(self, path: str):
        self.path = path
        super().__init__(path)


def _strict_json_value(line: str) -> Any:
    """Decode JSON while retaining object pairs long enough to reject duplicates."""
    parsed = json.loads(
        line,
        object_pairs_hook=lambda pairs: _JsonObjectPairs(tuple(pairs)),
    )

    def materialize(value: Any, path: str) -> Any:
        if isinstance(value, _JsonObjectPairs):
            result: dict[str, Any] = {}
            for key, nested in value.pairs:
                field_path = key if path == "$" else f"{path}.{key}"
                if key in result:
                    raise _DuplicateJsonKey(field_path)
                result[key] = materialize(nested, field_path)
            return result
        if isinstance(value, list):
            return [
                materialize(nested, f"{path}[{index}]")
                for index, nested in enumerate(value)
            ]
        return value

    return materialize(parsed, "$")


@dataclass(frozen=True, slots=True)
class MapPose:
    x: float
    y: float
    yaw: float | None = None

    def __post_init__(self) -> None:
        values = (self.x, self.y) if self.yaw is None else (self.x, self.y, self.yaw)
        if not all(math.isfinite(value) for value in values):
            raise PhysicalFeatureImportError("map pose values must be finite")


@dataclass(frozen=True, slots=True)
class WaypointFeature:
    source_id: str
    display_name: str
    rmf_waypoint_name: str
    location_code: str
    operational_role: str
    parent_location_code: str | None
    temperature_zone: str | None
    pose: MapPose


@dataclass(frozen=True, slots=True)
class BottleneckFeature:
    source_id: str
    display_name: str
    feature_code: str
    mutex_group: str
    pose: MapPose
    radius_m: float
    source_diameter_m: float


@dataclass(frozen=True, slots=True)
class FiducialBinding:
    source_id: str
    marker_id: int
    dictionary: str
    target_location_code: str
    recognition_pose: MapPose
    pixel_size: float


@dataclass(frozen=True, slots=True)
class PhysicalFeatureImport:
    map_name: str
    waypoints: tuple[WaypointFeature, ...]
    bottlenecks: tuple[BottleneckFeature, ...]
    fiducials: tuple[FiducialBinding, ...]

    def waypoint(self, location_code: str) -> WaypointFeature:
        for waypoint in self.waypoints:
            if waypoint.location_code == location_code:
                return waypoint
        raise KeyError(location_code)

    def marker(self, marker_id: int) -> FiducialBinding:
        for binding in self.fiducials:
            if binding.marker_id == marker_id:
                return binding
        raise KeyError(marker_id)


def _exact_fields(
    value: dict[str, Any],
    required: set[str] | frozenset[str],
    line_number: int,
    label: str = "record",
    optional: set[str] | frozenset[str] = frozenset(),
) -> None:
    missing = sorted(required - value.keys())
    if missing:
        field = missing[0]
        qualified = field if label == "record" else f"{label}.{field}"
        raise PhysicalFeatureImportError(
            f"line {line_number}: missing field {qualified}"
        )
    unexpected = sorted(value.keys() - required - optional)
    if unexpected:
        field = unexpected[0]
        qualified = field if label == "record" else f"{label}.{field}"
        raise PhysicalFeatureImportError(
            f"line {line_number}: unexpected field {qualified}"
        )


def _string_value(value: Any, field: str, line_number: int) -> str:
    if not isinstance(value, str) or not value:
        raise PhysicalFeatureImportError(
            f"line {line_number}: {field} must be a non-empty string"
        )
    if value != value.strip():
        raise PhysicalFeatureImportError(
            f"line {line_number}: {field} must not have surrounding whitespace"
        )
    return value


def _required_string(record: dict[str, Any], field: str, line_number: int) -> str:
    return _string_value(record.get(field), field, line_number)


def _identifier(record: dict[str, Any], field: str, line_number: int) -> str:
    value = _required_string(record, field, line_number)
    if any(character.isspace() for character in value):
        raise PhysicalFeatureImportError(
            f"line {line_number}: {field} must not contain whitespace"
        )
    return value


def _optional_string(
    record: dict[str, Any], field: str, line_number: int
) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    return _string_value(value, field, line_number)


def _optional_identifier(
    record: dict[str, Any], field: str, line_number: int
) -> str | None:
    value = _optional_string(record, field, line_number)
    if value is not None and any(character.isspace() for character in value):
        raise PhysicalFeatureImportError(
            f"line {line_number}: {field} must not contain whitespace"
        )
    return value


def _finite_number(value: Any, field: str, line_number: int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhysicalFeatureImportError(
            f"line {line_number}: {field} must be a finite number"
        )
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise PhysicalFeatureImportError(
            f"line {line_number}: {field} must be a finite number"
        ) from error
    if not math.isfinite(number):
        raise PhysicalFeatureImportError(
            f"line {line_number}: {field} must be a finite number"
        )
    return number


def _non_negative_integer(value: Any, field: str, line_number: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PhysicalFeatureImportError(
            f"line {line_number}: {field} must be a non-negative integer"
        )
    return value


def _map_pose(
    record: dict[str, Any], field: str, line_number: int, *, yaw_required: bool
) -> MapPose:
    value = record.get(field)
    if not isinstance(value, dict):
        raise PhysicalFeatureImportError(
            f"line {line_number}: {field} must be an object"
        )
    required = {"x", "y", "yaw"} if yaw_required else {"x", "y"}
    _exact_fields(value, required, line_number, field)
    return MapPose(
        x=_finite_number(value.get("x"), f"{field}.x", line_number),
        y=_finite_number(value.get("y"), f"{field}.y", line_number),
        yaw=(
            _finite_number(value.get("yaw"), f"{field}.yaw", line_number)
            if yaw_required
            else None
        ),
    )


def _source_labels(record: dict[str, Any], line_number: int) -> tuple[str, ...]:
    values = record.get("source_labels")
    if not isinstance(values, list) or not values:
        raise PhysicalFeatureImportError(
            f"line {line_number}: source_labels must be a non-empty array"
        )
    labels: list[str] = []
    for index, value in enumerate(values):
        label = _string_value(value, f"source_labels[{index}]", line_number)
        if any(character.isspace() for character in label):
            raise PhysicalFeatureImportError(
                f"line {line_number}: source_labels[{index}] must not contain whitespace"
            )
        if label in labels:
            raise PhysicalFeatureImportError(
                f"line {line_number}: duplicate source_labels[{index}]: {label}"
            )
        labels.append(label)
    return tuple(labels)


def _timestamp(value: Any, field: str, line_number: int) -> str:
    timestamp = _string_value(value, field, line_number)
    try:
        datetime.fromisoformat(timestamp)
    except ValueError as error:
        raise PhysicalFeatureImportError(
            f"line {line_number}: {field} must be an ISO-8601 timestamp"
        ) from error
    return timestamp


def _source_measurements(
    record: dict[str, Any],
    record_type: str,
    source_labels: tuple[str, ...],
    line_number: int,
) -> tuple[dict[str, Any], ...]:
    values = record.get("source_measurements")
    if not isinstance(values, list) or not values:
        raise PhysicalFeatureImportError(
            f"line {line_number}: source_measurements must be a non-empty array"
        )

    measurements: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        label = f"source_measurements[{index}]"
        if not isinstance(value, dict):
            raise PhysicalFeatureImportError(
                f"line {line_number}: {label} must be an object"
            )
        if record_type == "waypoint":
            _exact_fields(
                value,
                WAYPOINT_MEASUREMENT_FIELDS,
                line_number,
                label,
                optional={"marker_id"},
            )
        elif record_type == "bottleneck":
            _exact_fields(value, BOTTLENECK_MEASUREMENT_FIELDS, line_number, label)
        else:
            _exact_fields(value, FIDUCIAL_MEASUREMENT_FIELDS, line_number, label)

        _timestamp(value.get("timestamp"), f"{label}.timestamp", line_number)
        measurement_label = _string_value(
            value.get("label"), f"{label}.label", line_number
        )
        if measurement_label not in source_labels:
            raise PhysicalFeatureImportError(
                f"line {line_number}: {label}.label must match source_labels"
            )
        _string_value(value.get("note"), f"{label}.note", line_number)
        _finite_number(value.get("map_x"), f"{label}.map_x", line_number)
        _finite_number(value.get("map_y"), f"{label}.map_y", line_number)
        stddev = _finite_number(
            value.get("amcl_xy_stddev_m"),
            f"{label}.amcl_xy_stddev_m",
            line_number,
        )
        if stddev < 0:
            raise PhysicalFeatureImportError(
                f"line {line_number}: {label}.amcl_xy_stddev_m must be non-negative"
            )

        if record_type == "waypoint":
            yaw_source = record["yaw_source"]
            if yaw_source == "measured":
                _finite_number(value.get("map_yaw"), f"{label}.map_yaw", line_number)
            elif value.get("map_yaw") is not None:
                raise PhysicalFeatureImportError(
                    f"line {line_number}: {label}.map_yaw must be null when yaw_source is not_required"
                )
            if "marker_id" in value:
                _non_negative_integer(
                    value["marker_id"], f"{label}.marker_id", line_number
                )
        elif record_type == "bottleneck":
            diameter = _finite_number(
                value.get("source_diameter_m"),
                f"{label}.source_diameter_m",
                line_number,
            )
            if diameter <= 0:
                raise PhysicalFeatureImportError(
                    f"line {line_number}: {label}.source_diameter_m must be positive"
                )
        else:
            _non_negative_integer(
                value.get("marker_id"), f"{label}.marker_id", line_number
            )
            _string_value(value.get("dict"), f"{label}.dict", line_number)
            pixel_size = _finite_number(
                value.get("pixel_size"), f"{label}.pixel_size", line_number
            )
            if pixel_size <= 0:
                raise PhysicalFeatureImportError(
                    f"line {line_number}: {label}.pixel_size must be positive"
                )
            _finite_number(value.get("map_yaw"), f"{label}.map_yaw", line_number)
        measurements.append(value)
    return tuple(measurements)


def _unique(
    value: object, field: str, seen: set[object], line_number: int
) -> None:
    if value in seen:
        raise PhysicalFeatureImportError(
            f"line {line_number}: duplicate {field}: {value}"
        )
    seen.add(value)


def _record_type_and_schema(record: dict[str, Any], line_number: int) -> str:
    schema_version = record.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise PhysicalFeatureImportError(
            f"line {line_number}: schema_version must be integer 1"
        )
    record_type = _identifier(record, "record_type", line_number)
    if record_type == "waypoint":
        fields = WAYPOINT_FIELDS
    elif record_type == "bottleneck":
        fields = BOTTLENECK_FIELDS
    elif record_type == "fiducial_binding":
        fields = FIDUCIAL_FIELDS
    else:
        raise PhysicalFeatureImportError(
            f"line {line_number}: unsupported record_type: {record_type}"
        )
    _exact_fields(record, fields, line_number)
    return record_type


def _validate_common_provenance(
    record: dict[str, Any], record_type: str, line_number: int
) -> tuple[dict[str, Any], ...]:
    _identifier(record, "source_id", line_number)
    target_map_name = _identifier(record, "target_map_name", line_number)
    if not MAP_NAME_PATTERN.fullmatch(target_map_name):
        raise PhysicalFeatureImportError(
            f"line {line_number}: target_map_name has an invalid identifier format"
        )
    _required_string(record, "source_map_name", line_number)
    source_labels = _source_labels(record, line_number)
    return _source_measurements(record, record_type, source_labels, line_number)


def _require_selected_measurement(
    record: dict[str, Any],
    record_type: str,
    measurements: tuple[dict[str, Any], ...],
    pose: MapPose,
    line_number: int,
) -> None:
    def same_number(left: object, right: float | None) -> bool:
        if right is None:
            return left is None
        return isinstance(left, (int, float)) and not isinstance(left, bool) and float(left) == right

    for measurement in measurements:
        if not same_number(measurement["map_x"], pose.x) or not same_number(
            measurement["map_y"], pose.y
        ):
            continue
        if record_type == "waypoint":
            if record["yaw_source"] == "measured" and not same_number(
                measurement["map_yaw"], pose.yaw
            ):
                continue
        elif record_type == "bottleneck":
            if not same_number(
                measurement["source_diameter_m"],
                _finite_number(
                    record["source_diameter_m"], "source_diameter_m", line_number
                ),
            ):
                continue
        else:
            if (
                measurement["marker_id"] != record["marker_id"]
                or measurement["dict"] != record["dictionary"]
                or not same_number(
                    measurement["pixel_size"],
                    _finite_number(record["pixel_size"], "pixel_size", line_number),
                )
                or not same_number(measurement["map_yaw"], pose.yaw)
            ):
                continue
        return
    raise PhysicalFeatureImportError(
        f"line {line_number}: source_measurements must include the selected {record_type} values"
    )


class PhysicalFeatureImporter:
    """Parse source bytes or a path without deriving or substituting any pose."""

    def parse(self, source: bytes | bytearray | Path | str) -> PhysicalFeatureImport:
        if isinstance(source, (bytes, bytearray)):
            try:
                text = bytes(source).decode("utf-8")
            except UnicodeDecodeError as error:
                raise PhysicalFeatureImportError("source must be UTF-8 JSONL") from error
        else:
            try:
                text = Path(source).read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise PhysicalFeatureImportError("source must be UTF-8 JSONL") from error

        records: list[
            tuple[int, str, dict[str, Any], tuple[dict[str, Any], ...]]
        ] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                raise PhysicalFeatureImportError(
                    f"line {line_number}: blank JSONL records are not supported"
                )
            try:
                record = _strict_json_value(line)
            except _DuplicateJsonKey as error:
                raise PhysicalFeatureImportError(
                    f"line {line_number}: duplicate JSON key at {error.path}"
                ) from error
            except json.JSONDecodeError as error:
                raise PhysicalFeatureImportError(
                    f"line {line_number}: invalid JSON"
                ) from error
            if not isinstance(record, dict):
                raise PhysicalFeatureImportError(
                    f"line {line_number}: record must be a JSON object"
                )
            record_type = _record_type_and_schema(record, line_number)
            measurements = _validate_common_provenance(
                record, record_type, line_number
            )
            records.append((line_number, record_type, record, measurements))
        if not records:
            raise PhysicalFeatureImportError("physical-feature JSONL is empty")

        target_map_names = {
            _identifier(record, "target_map_name", line_number)
            for line_number, _, record, _ in records
        }
        if len(target_map_names) != 1:
            raise PhysicalFeatureImportError(
                "physical-feature records must use one target_map_name"
            )
        map_name = next(iter(target_map_names))

        waypoints: list[WaypointFeature] = []
        bottlenecks: list[BottleneckFeature] = []
        fiducials: list[FiducialBinding] = []
        source_ids: set[object] = set()
        business_codes: set[object] = set()
        rmf_names: set[object] = set()
        mutex_groups: set[object] = set()
        marker_ids: set[object] = set()
        fiducial_targets: set[object] = set()

        for line_number, record_type, record, measurements in records:
            source_id = _identifier(record, "source_id", line_number)
            _unique(source_id, "source_id", source_ids, line_number)
            if record_type == "waypoint":
                location_code = _identifier(record, "location_code", line_number)
                rmf_name = _identifier(record, "rmf_waypoint_name", line_number)
                _unique(location_code, "location_code", business_codes, line_number)
                _unique(rmf_name, "rmf_waypoint_name", rmf_names, line_number)
                role = _identifier(record, "operational_role", line_number)
                if role not in {"loading_dock", "safety_zone", "charging_station"}:
                    raise PhysicalFeatureImportError(
                        f"line {line_number}: unsupported operational_role: {role}"
                    )
                parent = _optional_identifier(
                    record, "parent_location_code", line_number
                )
                temperature = _optional_string(record, "temperature_zone", line_number)
                if temperature not in {None, "ambient", "chilled", "frozen"}:
                    raise PhysicalFeatureImportError(
                        f"line {line_number}: unsupported temperature_zone: {temperature}"
                    )
                if role == "loading_dock" and (parent is None or temperature is None):
                    raise PhysicalFeatureImportError(
                        f"line {line_number}: loading_dock requires parent_location_code and temperature_zone"
                    )
                if role != "loading_dock" and (parent is not None or temperature is not None):
                    raise PhysicalFeatureImportError(
                        f"line {line_number}: {role} forbids parent_location_code and temperature_zone"
                    )
                yaw_source = _identifier(record, "yaw_source", line_number)
                if yaw_source not in {"measured", "not_required"}:
                    raise PhysicalFeatureImportError(
                        f"line {line_number}: unsupported yaw_source: {yaw_source}"
                    )
                if record["departure_pose"] is not None:
                    raise PhysicalFeatureImportError(
                        f"line {line_number}: departure_pose must be null in schema_version 1"
                    )
                pose = _map_pose(record, "map_pose", line_number, yaw_required=True)
                _require_selected_measurement(
                    record, record_type, measurements, pose, line_number
                )
                waypoints.append(
                    WaypointFeature(
                        source_id=source_id,
                        display_name=_required_string(record, "display_name", line_number),
                        rmf_waypoint_name=rmf_name,
                        location_code=location_code,
                        operational_role=role,
                        parent_location_code=parent,
                        temperature_zone=temperature,
                        pose=pose,
                    )
                )
            elif record_type == "bottleneck":
                feature_code = _identifier(record, "feature_code", line_number)
                mutex_group = _identifier(record, "mutex_group", line_number)
                _unique(feature_code, "feature_code", business_codes, line_number)
                _unique(mutex_group, "mutex_group", mutex_groups, line_number)
                radius_m = _finite_number(record.get("radius_m"), "radius_m", line_number)
                source_diameter_m = _finite_number(
                    record.get("source_diameter_m"), "source_diameter_m", line_number
                )
                if radius_m <= 0 or source_diameter_m <= 0:
                    raise PhysicalFeatureImportError(
                        f"line {line_number}: bottleneck dimensions must be positive"
                    )
                if not math.isclose(
                    radius_m,
                    source_diameter_m / 2,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                ):
                    raise PhysicalFeatureImportError(
                        f"line {line_number}: radius_m must be half of source_diameter_m"
                    )
                pose = _map_pose(record, "map_pose", line_number, yaw_required=False)
                _require_selected_measurement(
                    record, record_type, measurements, pose, line_number
                )
                bottlenecks.append(
                    BottleneckFeature(
                        source_id=source_id,
                        display_name=_required_string(record, "display_name", line_number),
                        feature_code=feature_code,
                        mutex_group=mutex_group,
                        pose=pose,
                        radius_m=radius_m,
                        source_diameter_m=source_diameter_m,
                    )
                )
            else:
                marker_id = _non_negative_integer(
                    record.get("marker_id"), "marker_id", line_number
                )
                _unique(marker_id, "marker_id", marker_ids, line_number)
                target = _identifier(record, "target_location_code", line_number)
                _unique(
                    target,
                    "fiducial target_location_code",
                    fiducial_targets,
                    line_number,
                )
                pixel_size = _finite_number(
                    record.get("pixel_size"), "pixel_size", line_number
                )
                if pixel_size <= 0:
                    raise PhysicalFeatureImportError(
                        f"line {line_number}: pixel_size must be positive"
                    )
                recognition_pose = _map_pose(
                    record, "recognition_pose", line_number, yaw_required=True
                )
                _require_selected_measurement(
                    record,
                    record_type,
                    measurements,
                    recognition_pose,
                    line_number,
                )
                fiducials.append(
                    FiducialBinding(
                        source_id=source_id,
                        marker_id=marker_id,
                        dictionary=_identifier(record, "dictionary", line_number),
                        target_location_code=target,
                        recognition_pose=recognition_pose,
                        pixel_size=pixel_size,
                    )
                )

        unknown_targets = {
            binding.target_location_code for binding in fiducials
        } - {waypoint.location_code for waypoint in waypoints}
        if unknown_targets:
            raise PhysicalFeatureImportError(
                "fiducial target_location_code is not a waypoint: "
                + ", ".join(sorted(unknown_targets))
            )

        counts = (len(waypoints), len(bottlenecks), len(fiducials))
        if map_name == CANONICAL_P0_MAP_NAME:
            if counts != CANONICAL_P0_COUNTS:
                raise PhysicalFeatureImportError(
                    "trihouse_test_01 requires exactly 8 waypoints, 2 bottlenecks, "
                    "and 3 fiducials"
                )
            targets = frozenset(
                binding.target_location_code for binding in fiducials
            )
            if targets != CANONICAL_P0_FIDUCIAL_TARGETS:
                raise PhysicalFeatureImportError(
                    "canonical fiducial target_location_code bindings must cover "
                    "the three warehouse docks exactly once"
                )

        return PhysicalFeatureImport(
            map_name=map_name,
            waypoints=tuple(waypoints),
            bottlenecks=tuple(bottlenecks),
            fiducials=tuple(fiducials),
        )
