"""Strict import of measured map waypoints, bottlenecks, and fiducial bindings."""

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any


CANONICAL_P0_MAP_NAME = "trihouse_test_01"
CANONICAL_P0_COUNTS = (8, 2, 3)


class PhysicalFeatureImportError(ValueError):
    """Raised when a physical-feature JSONL source violates its data contract."""


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


def _required_string(record: dict[str, Any], field: str, line_number: int) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PhysicalFeatureImportError(
            f"line {line_number}: {field} must be a non-empty string"
        )
    return value


def _optional_string(
    record: dict[str, Any], field: str, line_number: int
) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PhysicalFeatureImportError(
            f"line {line_number}: {field} must be null or a non-empty string"
        )
    return value


def _finite_number(value: Any, label: str, line_number: int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhysicalFeatureImportError(
            f"line {line_number}: {label} must be a finite number"
        )
    number = float(value)
    if not math.isfinite(number):
        raise PhysicalFeatureImportError(
            f"line {line_number}: {label} must be a finite number"
        )
    return number


def _reject_non_finite(value: Any, label: str, line_number: int) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise PhysicalFeatureImportError(
            f"line {line_number}: {label} must contain only finite numbers"
        )
    if isinstance(value, dict):
        for key, nested in value.items():
            _reject_non_finite(nested, f"{label}.{key}", line_number)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_non_finite(nested, f"{label}[{index}]", line_number)


def _map_pose(
    record: dict[str, Any], field: str, line_number: int, *, yaw_required: bool
) -> MapPose:
    value = record.get(field)
    if not isinstance(value, dict):
        raise PhysicalFeatureImportError(
            f"line {line_number}: {field} must be an object"
        )
    x = _finite_number(value.get("x"), f"{field}.x", line_number)
    y = _finite_number(value.get("y"), f"{field}.y", line_number)
    yaw_value = value.get("yaw")
    if yaw_required:
        yaw = _finite_number(yaw_value, f"{field}.yaw", line_number)
    elif yaw_value is None:
        yaw = None
    else:
        yaw = _finite_number(yaw_value, f"{field}.yaw", line_number)
    return MapPose(x=x, y=y, yaw=yaw)


def _unique(value: object, label: str, seen: set[object]) -> None:
    if value in seen:
        raise PhysicalFeatureImportError(f"duplicate {label}: {value}")
    seen.add(value)


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

        records: list[tuple[int, dict[str, Any]]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                raise PhysicalFeatureImportError(
                    f"line {line_number}: blank JSONL records are not supported"
                )
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise PhysicalFeatureImportError(
                    f"line {line_number}: invalid JSON"
                ) from error
            if not isinstance(record, dict):
                raise PhysicalFeatureImportError(
                    f"line {line_number}: record must be a JSON object"
                )
            _reject_non_finite(record, "record", line_number)
            if record.get("schema_version") != 1:
                raise PhysicalFeatureImportError(
                    f"line {line_number}: schema_version must be 1"
                )
            records.append((line_number, record))
        if not records:
            raise PhysicalFeatureImportError("physical-feature JSONL is empty")

        target_map_names = {
            _required_string(record, "target_map_name", line_number)
            for line_number, record in records
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
        location_codes: set[object] = set()
        rmf_names: set[object] = set()
        feature_codes: set[object] = set()
        mutex_groups: set[object] = set()
        marker_ids: set[object] = set()

        for line_number, record in records:
            source_id = _required_string(record, "source_id", line_number)
            _unique(source_id, "source_id", source_ids)
            record_type = _required_string(record, "record_type", line_number)
            if record_type == "waypoint":
                location_code = _required_string(record, "location_code", line_number)
                rmf_name = _required_string(record, "rmf_waypoint_name", line_number)
                _unique(location_code, "location_code", location_codes)
                _unique(rmf_name, "rmf_waypoint_name", rmf_names)
                waypoints.append(
                    WaypointFeature(
                        source_id=source_id,
                        display_name=_required_string(record, "display_name", line_number),
                        rmf_waypoint_name=rmf_name,
                        location_code=location_code,
                        operational_role=_required_string(
                            record, "operational_role", line_number
                        ),
                        parent_location_code=_optional_string(
                            record, "parent_location_code", line_number
                        ),
                        temperature_zone=_optional_string(
                            record, "temperature_zone", line_number
                        ),
                        pose=_map_pose(
                            record, "map_pose", line_number, yaw_required=True
                        ),
                    )
                )
            elif record_type == "bottleneck":
                feature_code = _required_string(record, "feature_code", line_number)
                mutex_group = _required_string(record, "mutex_group", line_number)
                _unique(feature_code, "feature_code", feature_codes)
                _unique(mutex_group, "mutex_group", mutex_groups)
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
                bottlenecks.append(
                    BottleneckFeature(
                        source_id=source_id,
                        display_name=_required_string(record, "display_name", line_number),
                        feature_code=feature_code,
                        mutex_group=mutex_group,
                        pose=_map_pose(
                            record, "map_pose", line_number, yaw_required=False
                        ),
                        radius_m=radius_m,
                        source_diameter_m=source_diameter_m,
                    )
                )
            elif record_type == "fiducial_binding":
                marker_id = record.get("marker_id")
                if isinstance(marker_id, bool) or not isinstance(marker_id, int) or marker_id < 0:
                    raise PhysicalFeatureImportError(
                        f"line {line_number}: marker_id must be a non-negative integer"
                    )
                _unique(marker_id, "marker_id", marker_ids)
                pixel_size = _finite_number(
                    record.get("pixel_size"), "pixel_size", line_number
                )
                if pixel_size <= 0:
                    raise PhysicalFeatureImportError(
                        f"line {line_number}: pixel_size must be positive"
                    )
                fiducials.append(
                    FiducialBinding(
                        source_id=source_id,
                        marker_id=marker_id,
                        dictionary=_required_string(record, "dictionary", line_number),
                        target_location_code=_required_string(
                            record, "target_location_code", line_number
                        ),
                        recognition_pose=_map_pose(
                            record, "recognition_pose", line_number, yaw_required=True
                        ),
                        pixel_size=pixel_size,
                    )
                )
            else:
                raise PhysicalFeatureImportError(
                    f"line {line_number}: unsupported record_type: {record_type}"
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
        if map_name == CANONICAL_P0_MAP_NAME and counts != CANONICAL_P0_COUNTS:
            raise PhysicalFeatureImportError(
                "trihouse_test_01 requires exactly 8 waypoints, 2 bottlenecks, "
                "and 3 fiducials"
            )

        return PhysicalFeatureImport(
            map_name=map_name,
            waypoints=tuple(waypoints),
            bottlenecks=tuple(bottlenecks),
            fiducials=tuple(fiducials),
        )
