"""Queries used by the first control-system vertical slice."""


import base64
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
from typing import Any, Protocol
import uuid
from zoneinfo import ZoneInfo

import yaml

from .database import Database


SEOUL = ZoneInfo("Asia/Seoul")


class FmsRepository(Protocol):
    def ping(self) -> bool: ...

    def list_devices(self) -> list[dict[str, object]]: ...

    def list_inventory(self) -> list[dict[str, object]]: ...

    def list_jobs(self) -> list[dict[str, object]]: ...

    def create_job(self, job: dict[str, Any]) -> dict[str, Any]: ...

    def get_job(self, job_id: int) -> dict[str, Any] | None: ...

    def get_job_timeline(self, job_id: int) -> list[dict[str, Any]] | None: ...

    def dispatch_step(
        self, job_step_id: int, request: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]: ...

    def claim_command(
        self, rmf_task_id: str, request: dict[str, Any]
    ) -> dict[str, Any]: ...

    def claim_rmf_dispatches(self, worker_id: str, limit: int) -> list[dict[str, Any]]: ...

    def record_rmf_dispatch_acceptance(
        self, message_id: str, acceptance: dict[str, Any]
    ) -> dict[str, Any]: ...

    def list_registered_robot_ids(self) -> set[str]: ...

    def ingest_robot_status(self, status: dict[str, Any]) -> None: ...

    def ingest_task_event(self, event: dict[str, Any]) -> dict[str, Any]: ...

    def adjust_inventory(
        self,
        lot_id: int,
        quantity_delta: int,
        recorded_by: str,
        note: str | None,
        idempotency_key: str,
    ) -> dict[str, object]: ...

    def list_map_projects(self) -> list[dict[str, Any]]: ...

    def get_map_project(self, map_name: str) -> dict[str, Any] | None: ...

    def get_public_map_draft(self, map_name: str) -> dict[str, Any] | None: ...

    def store_map_project_source(
        self, map_name: str, source: dict[str, Any]
    ) -> dict[str, Any]: ...

    def get_map_project_source(
        self, map_name: str, source_uuid: str
    ) -> dict[str, Any] | None: ...

    def save_public_map_draft(
        self,
        map_name: str,
        draft: dict[str, Any],
        expected_revision: int,
        staged_sources: list[dict[str, Any]],
    ) -> dict[str, Any]: ...

    def delete_public_map_draft(self, map_name: str) -> None: ...

    def active_revision(self, map_name: str) -> str | None: ...

    def deployment_failure_events(self, map_name: str) -> list[dict[str, Any]]: ...

    def save_map_project(
        self, map_name: str, project: dict[str, Any], expected_revision: int | None
    ) -> dict[str, Any]: ...

    def delete_map_project(self, map_name: str) -> None: ...

    def validate_map_project(self, map_name: str) -> dict[str, Any]: ...

    def publish_map_project(
        self, map_name: str, publication: dict[str, Any]
    ) -> dict[str, Any]: ...

    def get_published_map(self, map_name: str) -> dict[str, Any] | None: ...

    def list_projected_map_features(self, map_revision: str) -> list[dict[str, Any]]: ...


class InventoryLotNotFound(Exception):
    pass


class InventoryQuantityConflict(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


class JobNotFound(Exception):
    pass


class JobStepNotFound(Exception):
    pass


class JobStepNotDispatchable(Exception):
    pass


class CommandClaimConflict(Exception):
    pass


class DispatchMessageNotFound(Exception):
    pass


class RuntimeContextConflict(Exception):
    pass


class MapProjectNotFound(Exception):
    pass


class MapProjectSourceValidationError(ValueError):
    """Stable domain error for invalid immutable map-source input."""


class MapDraftRevisionConflict(Exception):
    pass


class MapRevisionContentConflict(Exception):
    pass


class MapProjectValidationError(Exception):
    pass


class PublishedMapProjectDeleteConflict(Exception):
    pass


MAP_PROJECT_SOURCE_TYPES = frozenset(
    {"slam_yaml", "slam_image", "floor_plan", "physical_features_import"}
)
JSON_SAFE_INTEGER_MAX = 2**53 - 1


def _canonical_source_metadata(metadata: object) -> dict[str, Any] | None:
    """Return detached JSON object data or one backend-independent domain error."""
    if metadata is None:
        return None
    if not isinstance(metadata, dict):
        raise MapProjectSourceValidationError("metadata must be an object or null")

    active_containers: set[int] = set()

    def canonical(value: object, path: str) -> Any:
        if value is None or isinstance(value, (str, bool)):
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            if not -JSON_SAFE_INTEGER_MAX <= value <= JSON_SAFE_INTEGER_MAX:
                raise MapProjectSourceValidationError(
                    f"metadata {path} must be an I-JSON safe integer between "
                    f"{-JSON_SAFE_INTEGER_MAX} and {JSON_SAFE_INTEGER_MAX}"
                )
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise MapProjectSourceValidationError(
                    f"metadata {path} must contain only finite numbers"
                )
            return value
        if isinstance(value, dict):
            identity = id(value)
            if identity in active_containers:
                raise MapProjectSourceValidationError(
                    f"metadata {path} must not contain cycles"
                )
            active_containers.add(identity)
            try:
                result: dict[str, Any] = {}
                for key, nested in value.items():
                    if not isinstance(key, str):
                        raise MapProjectSourceValidationError(
                            f"metadata {path} must use string object keys"
                        )
                    result[key] = canonical(nested, f"{path}.{key}")
                return result
            finally:
                active_containers.remove(identity)
        if isinstance(value, (list, tuple)):
            identity = id(value)
            if identity in active_containers:
                raise MapProjectSourceValidationError(
                    f"metadata {path} must not contain cycles"
                )
            active_containers.add(identity)
            try:
                return [
                    canonical(nested, f"{path}[{index}]")
                    for index, nested in enumerate(value)
                ]
            finally:
                active_containers.remove(identity)
        raise MapProjectSourceValidationError(
            f"metadata {path} contains a non-JSON value"
        )

    try:
        canonical_metadata = canonical(metadata, "$")
        encoded = json.dumps(
            canonical_metadata,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        return json.loads(encoded)
    except MapProjectSourceValidationError:
        raise
    except (OverflowError, RecursionError, TypeError, ValueError) as error:
        raise MapProjectSourceValidationError(
            "metadata must be finite JSON-serializable object data"
        ) from error


def _new_map_project_source(source: dict[str, Any]) -> dict[str, Any]:
    """Validate immutable source input and derive its identity metadata from bytes."""
    source_type = source.get("source_type")
    if source_type not in MAP_PROJECT_SOURCE_TYPES:
        raise MapProjectSourceValidationError("unsupported map project source_type")
    file_name = source.get("file_name")
    if not isinstance(file_name, str) or not file_name or len(file_name) > 255:
        raise MapProjectSourceValidationError(
            "file_name must be between 1 and 255 characters"
        )
    mime_type = source.get("mime_type")
    if not isinstance(mime_type, str) or not mime_type or len(mime_type) > 128:
        raise MapProjectSourceValidationError(
            "mime_type must be between 1 and 128 characters"
        )
    content = source.get("content_bytes")
    if not isinstance(content, (bytes, bytearray)) or not content:
        raise MapProjectSourceValidationError("content_bytes must be non-empty bytes")
    metadata = _canonical_source_metadata(source.get("metadata"))
    content_bytes = bytes(content)
    source_uuid = source.get("source_uuid") or str(uuid.uuid4())
    try:
        source_uuid = str(uuid.UUID(str(source_uuid)))
    except (AttributeError, TypeError, ValueError) as error:
        raise MapProjectSourceValidationError("source_uuid must be a UUID") from error
    return {
        "source_uuid": source_uuid,
        "source_type": source_type,
        "file_name": file_name,
        "mime_type": mime_type,
        "content_bytes": content_bytes,
        "sha256": hashlib.sha256(content_bytes).hexdigest(),
        "byte_size": len(content_bytes),
        "metadata": metadata,
    }


PROJECT1_LOCATION_CODES = {
    "픽업1": "A-SLOT-01",
    "드랍오프1": "OUT-DOCK-01",
    "충전1": "CHG-01",
    "충전2": "CHG-02",
    "대기1": "IN-WAIT-01",
    "대기3": "NARROW-WAIT-01",
    "설비1": "OMX-WS-01",
    "설비2": "OMX-WS-02",
}


def _same_point(left: object, right: object) -> bool:
    if not isinstance(left, list) or not isinstance(right, list):
        return False
    if len(left) < 2 or len(right) < 2:
        return False
    return float(left[0]) == float(right[0]) and float(left[1]) == float(right[1])


def _normalize_map_payload(
    map_name: str,
    payload: dict[str, Any],
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    """Normalize waypoint identity and discard deprecated user-authored lanes."""
    normalized = deepcopy(payload)
    normalized["mapName"] = map_name
    normalized.pop("laneDirections", None)
    waypoints = normalized.setdefault("waypoints", [])
    previous_waypoints = (
        existing.get("payload", {}).get("waypoints", []) if existing else []
    )
    for index, waypoint in enumerate(waypoints):
        previous = previous_waypoints[index] if index < len(previous_waypoints) else {}
        waypoint["waypointUuid"] = (
            waypoint.get("waypointUuid")
            or (
                previous.get("waypointUuid")
                if _same_point(waypoint.get("point"), previous.get("point"))
                else None
            )
            or str(uuid.uuid4())
        )
        waypoint["rmfWaypointName"] = waypoint.get("rmfWaypointName") or waypoint.get(
            "name", ""
        )
        if (
            not waypoint.get("locationCode")
            and previous.get("locationCode")
            and _same_point(waypoint.get("point"), previous.get("point"))
        ):
            waypoint["locationCode"] = previous["locationCode"]
        if not waypoint.get("locationCode") and map_name == "project1":
            waypoint["locationCode"] = PROJECT1_LOCATION_CODES.get(
                waypoint["rmfWaypointName"]
            )
        if (
            not waypoint.get("mapPose")
            and previous.get("mapPose")
            and _same_point(waypoint.get("point"), previous.get("point"))
        ):
            waypoint["mapPose"] = deepcopy(previous["mapPose"])
    for zone in normalized.setdefault("bottleneckZones", []):
        zone["featureType"] = zone.get("featureType") or "bottleneck"
    return normalized


def _public_draft_payload(map_name: str, draft: dict[str, Any]) -> dict[str, Any]:
    """Translate the public point+yaw surface to the established authoring payload."""
    public_waypoints = deepcopy(draft.get("waypoints", []))
    public_features = deepcopy(draft.get("features", []))
    waypoints: list[dict[str, Any]] = []
    for waypoint in public_waypoints:
        x = float(waypoint["x"])
        y = float(waypoint["y"])
        yaw = float(waypoint["yaw"])
        role = waypoint.get("operational_role")
        category = {
            "loading_dock": "픽업",
            "safety_zone": "대기",
            "charging_station": "충전",
        }.get(role, "일반")
        rmf_name = waypoint.get("rmf_waypoint_name") or waypoint["code"]
        waypoints.append(
            {
                "point": [x, y],
                "mapPose": [x, y, yaw],
                "yaw": yaw,
                "name": waypoint.get("display_name") or rmf_name,
                "rmfWaypointName": rmf_name,
                "category": category,
                **(
                    {"locationCode": waypoint["location_code"]}
                    if waypoint.get("location_code")
                    else {}
                ),
                **(
                    {"parentLocationCode": waypoint["parent_location_code"]}
                    if waypoint.get("parent_location_code")
                    else {}
                ),
                **(
                    {"temperatureZone": waypoint["temperature_zone"]}
                    if waypoint.get("temperature_zone")
                    else {}
                ),
            }
        )
    bottlenecks = [
        {
            "featureType": "bottleneck",
            "featureCode": feature["feature_code"],
            "displayName": feature.get("display_name") or feature["feature_code"],
            "mutexGroup": feature["mutex_group"],
            "mapPose": [float(feature["x"]), float(feature["y"])],
            "radiusM": float(feature["radius_m"]),
        }
        for feature in public_features
        if feature.get("type") == "bottleneck"
    ]
    fiducials = [
        {
            "featureCode": feature["code"],
            "markerId": int(feature["marker_id"]),
            "dictionary": feature["dictionary"],
            "targetLocationCode": feature["target_location_code"],
            "recognitionPose": [
                float(feature["x"]),
                float(feature["y"]),
                float(feature["yaw"]),
            ],
            "pixelSize": float(feature["pixel_size"]),
        }
        for feature in public_features
        if feature.get("type") == "fiducial_binding"
    ]
    return {
        "format": "trihouse-map-draft",
        "version": int(draft["format_version"]),
        "mapName": map_name,
        "sourceUuids": deepcopy(draft.get("source_uuids", {})),
        "runtimeProfileHash": draft["runtime_profile_hash"],
        "publicWaypoints": public_waypoints,
        "publicFeatures": public_features,
        "waypoints": waypoints,
        "bottleneckZones": bottlenecks,
        "fiducialBindings": fiducials,
    }


def _public_draft_from_project(project: dict[str, Any]) -> dict[str, Any]:
    payload = project["payload"]
    return {
        "map_name": project["map_name"],
        "format_version": int(project["format_version"]),
        "draft_revision": int(project["draft_revision"]),
        "source_uuids": deepcopy(payload.get("sourceUuids", {})),
        "staged_source_tokens": {},
        "waypoints": deepcopy(payload.get("publicWaypoints", [])),
        "features": deepcopy(payload.get("publicFeatures", [])),
        "runtime_profile_hash": payload.get("runtimeProfileHash", ""),
    }


def _public_feature_projection(
    map_name: str,
    map_revision: str,
    feature: dict[str, Any],
) -> dict[str, Any]:
    if feature["type"] == "bottleneck":
        return {
            "map_name": map_name,
            "map_revision": map_revision,
            "feature_code": feature["feature_code"],
            "feature_type": "bottleneck",
            "location_id": None,
            "marker_code": None,
            "geometry": {
                "type": "Point",
                "coordinates": [float(feature["x"]), float(feature["y"])],
            },
            "properties": {
                "radius_m": float(feature["radius_m"]),
                "mutex_group": feature["mutex_group"],
            },
            "active": True,
        }
    return {
        "map_name": map_name,
        "map_revision": map_revision,
        "feature_code": feature["code"],
        "feature_type": "fiducial",
        "location_id": None,
        "marker_code": int(feature["marker_id"]),
        "geometry": {
            "type": "Point",
            "coordinates": [float(feature["x"]), float(feature["y"])],
        },
        "properties": {
            "dictionary": feature["dictionary"],
            "target_location_code": feature["target_location_code"],
            "recognition_yaw": float(feature["yaw"]),
            "pixel_size": float(feature["pixel_size"]),
        },
        "active": True,
    }


def _validate_map_draft(project: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    waypoints = project["payload"].get("waypoints", [])
    waypoint_ids: set[str] = set()
    names: set[str] = set()
    location_codes: set[str] = set()
    for waypoint in waypoints:
        waypoint_id = waypoint.get("waypointUuid")
        try:
            parsed_waypoint_id = str(uuid.UUID(str(waypoint_id)))
        except (ValueError, TypeError, AttributeError):
            parsed_waypoint_id = ""
            errors.append(f"{waypoint_id}: waypointUuid 형식이 잘못됐습니다")
        if parsed_waypoint_id in waypoint_ids:
            errors.append(f"{waypoint_id}: waypointUuid가 중복됩니다")
        if parsed_waypoint_id:
            waypoint_ids.add(parsed_waypoint_id)
        name = waypoint.get("rmfWaypointName") or waypoint.get("name", "")
        if not name or name in names:
            errors.append(f"{name or '<이름 없음>'}: Waypoint 이름이 중복되거나 비었습니다")
        names.add(name)
        location_code = waypoint.get("locationCode")
        if waypoint.get("category") != "일반" and not location_code:
            errors.append(f"{name}: locationCode가 필요합니다")
        if location_code and location_code in location_codes:
            errors.append(f"{location_code}: locationCode가 중복됩니다")
        if location_code:
            location_codes.add(location_code)
            map_pose = waypoint.get("mapPose")
            if (
                not isinstance(map_pose, list)
                or len(map_pose) != 3
                or not all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))
                    for value in map_pose
                )
            ):
                errors.append(f"{name}: publish용 mapPose(m)가 필요합니다")
    waypoint_categories = {
        (waypoint.get("rmfWaypointName") or waypoint.get("name")): waypoint.get("category")
        for waypoint in waypoints
    }
    robot_ids: set[str] = set()
    for robot in project.get("robots", []):
        robot_id = robot.get("robot_id", "")
        if not robot_id or robot_id in robot_ids:
            errors.append(f"{robot_id or '<ID 없음>'}: 로봇 ID가 중복되거나 비었습니다")
        robot_ids.add(robot_id)
        station = robot.get("charger_waypoint_name")
        required_category = "충전" if robot.get("kind") == "mobile" else "설비"
        if not station or waypoint_categories.get(station) != required_category:
            errors.append(
                f"{robot_id}: {required_category} Waypoint 연결이 필요합니다"
            )
        if robot.get("kind") == "mobile" and project.get("fleet") is None:
            errors.append(f"{robot_id}: mobile robot에는 fleet 설정이 필요합니다")
    return errors


def _validate_publication_artifacts(
    project: dict[str, Any], publication: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    contents = {
        "building_sha256": publication["building_yaml_content"],
        "nav_graph_sha256": publication["nav_graph_yaml_content"],
        "world_sha256": publication["world_content"],
    }
    for hash_key, content in contents.items():
        actual = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if actual != publication[hash_key]:
            errors.append(f"{hash_key}: artifact 내용과 SHA-256이 다릅니다")
    hash_identity = {
        key: publication[key]
        for key in ("building_sha256", "nav_graph_sha256", "world_sha256")
    }
    expected_suffix = hashlib.sha256(
        json.dumps(hash_identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if publication["map_revision"] != f'{project["map_name"]}:{expected_suffix}':
        errors.append("map_revision이 artifact content hash와 다릅니다")
    if (
        project["payload"].get("format") != "trihouse-map-draft"
        and project.get("building_yaml") != publication["building_yaml_content"]
    ):
        errors.append("building YAML이 현재 draft와 다릅니다")
    try:
        nav_graph = yaml.safe_load(publication["nav_graph_yaml_content"])
    except yaml.YAMLError:
        errors.append("nav graph YAML을 파싱할 수 없습니다")
        return errors
    named_vertices: dict[str, tuple[float, float]] = {}
    for level in (nav_graph or {}).get("levels", {}).values():
        for vertex in level.get("vertices", []):
            if len(vertex) < 3 or not isinstance(vertex[2], dict):
                continue
            name = vertex[2].get("name")
            if name:
                named_vertices[str(name)] = (float(vertex[0]), float(vertex[1]))
    for waypoint in project["payload"].get("waypoints", []):
        if not waypoint.get("locationCode"):
            continue
        # Workcells are fixed equipment positions, not traversable RMF graph vertices.
        if waypoint.get("category") == "설비":
            continue
        name = waypoint.get("rmfWaypointName") or waypoint.get("name")
        map_pose = waypoint.get("mapPose") or []
        actual = named_vertices.get(name)
        if actual is None:
            errors.append(f"{name}: nav graph named vertex가 없습니다")
        elif len(map_pose) < 2 or any(
            abs(float(map_pose[index]) - actual[index]) > 1e-6 for index in (0, 1)
        ):
            errors.append(f"{name}: mapPose가 nav graph 좌표와 다릅니다")
    return errors


def _json(value: object) -> object:
    return json.loads(value) if isinstance(value, str) else value


def _mysql_datetime(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(SEOUL).replace(tzinfo=None)


def _seoul_datetimes(row: dict[str, object]) -> dict[str, object]:
    for key, value in row.items():
        if isinstance(value, datetime) and value.tzinfo is None:
            row[key] = value.replace(tzinfo=SEOUL)
    return row


class MySqlFmsRepository:
    def __init__(self, database: Database):
        self.database = database

    def _all(
        self, sql: str, params: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(sql, params)
                return [_seoul_datetimes(dict(row)) for row in cursor.fetchall()]
            finally:
                cursor.close()

    def ping(self) -> bool:
        with self.database.connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT 1")
                return cursor.fetchone() == (1,)
            finally:
                cursor.close()

    def list_devices(self) -> list[dict[str, object]]:
        return self._all(
            """
            SELECT d.device_id, d.device_type, d.name, d.control_mode,
                   ds.state, ds.health, ds.battery_pct, ds.observed_at
            FROM devices d
            LEFT JOIN device_states ds ON ds.device_id = d.device_id
            WHERE d.active = 1
            ORDER BY d.device_type, d.device_id
            """
        )

    def list_registered_robot_ids(self) -> set[str]:
        return {
            str(row["device_id"])
            for row in self._all(
                "SELECT device_id FROM devices WHERE device_type = 'mobile' AND active = 1"
            )
        }

    @staticmethod
    def _map_summary_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "map_name": row["map_name"],
            "drawing_name": row["drawing_name"],
            "format_version": int(row["format_version"]),
            "waypoint_count": int(row["waypoint_count"]),
            "lane_count": 0,
            "draft_revision": int(row["draft_revision"]),
            "has_building_yaml": bool(row["has_building_yaml"]),
            "updated_at": row["updated_at"],
        }

    def list_map_projects(self) -> list[dict[str, Any]]:
        rows = self._all(
            """
            SELECT map_name, drawing_name, format_version, waypoint_count,
                   draft_revision, building_yaml IS NOT NULL AS has_building_yaml,
                   updated_at
            FROM map_projects
            ORDER BY map_name
            """
        )
        return [self._map_summary_row(row) for row in rows]

    @staticmethod
    def _load_map_project(connection, map_name: str) -> dict[str, Any] | None:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT project_id, map_name, drawing_name, format_version, payload,
                       building_yaml, building_yaml_name, waypoint_count,
                       draft_revision,
                       building_yaml IS NOT NULL AS has_building_yaml, updated_at
                FROM map_projects WHERE map_name = %s
                """,
                (map_name,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            project_id = int(row["project_id"])
            cursor.execute(
                """
                SELECT file_name, kind, description, executable, content
                FROM map_project_files WHERE project_id = %s ORDER BY file_name
                """,
                (project_id,),
            )
            files = [dict(value) for value in cursor.fetchall()]
            for value in files:
                value["executable"] = bool(value["executable"])
            cursor.execute(
                """
                SELECT fleet_name, settings FROM map_project_fleets
                WHERE project_id = %s
                """,
                (project_id,),
            )
            fleet_row = cursor.fetchone()
            fleet = (
                {
                    "fleet_name": fleet_row["fleet_name"],
                    "settings": _json(fleet_row["settings"]),
                }
                if fleet_row
                else None
            )
            cursor.execute(
                """
                SELECT r.robot_id, r.seq, r.display_name, r.model, r.kind,
                       r.data_source, r.gz_name, r.zones, w.rmf_waypoint_name
                         AS charger_waypoint_name,
                       r.spawn_x, r.spawn_y, r.spawn_heading
                FROM map_project_robots r
                LEFT JOIN map_project_waypoints w
                  ON w.waypoint_uuid = r.charger_waypoint_uuid
                WHERE r.project_id = %s ORDER BY r.seq
                """,
                (project_id,),
            )
            robots = [dict(value) for value in cursor.fetchall()]
            for robot in robots:
                robot["zones"] = _json(robot["zones"])
            return {
                "map_name": row["map_name"],
                "drawing_name": row["drawing_name"],
                "format_version": int(row["format_version"]),
                "payload": _json(row["payload"]),
                "building_yaml": row["building_yaml"],
                "building_yaml_name": row["building_yaml_name"],
                "waypoint_count": int(row["waypoint_count"]),
                "lane_count": 0,
                "draft_revision": int(row["draft_revision"]),
                "has_building_yaml": bool(row["has_building_yaml"]),
                "updated_at": _seoul_datetimes({"value": row["updated_at"]})["value"],
                "files": files,
                "fleet": fleet,
                "robots": robots,
            }
        finally:
            cursor.close()

    def get_map_project(self, map_name: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            return self._load_map_project(connection, map_name)

    def get_public_map_draft(self, map_name: str) -> dict[str, Any] | None:
        project = self.get_map_project(map_name)
        if project is None:
            return None
        return _public_draft_from_project(project)

    def _save_public_map_draft_on_connection(
        self,
        connection,
        map_name: str,
        draft: dict[str, Any],
        expected_revision: int,
        staged_sources: list[dict[str, Any]],
        *,
        revision_override: int | None = None,
    ) -> dict[str, Any]:
        prepared_sources = [_new_map_project_source(value) for value in staged_sources]
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT project_id, payload, draft_revision
                FROM map_projects WHERE map_name = %s FOR UPDATE
                """,
                (map_name,),
            )
            current = cursor.fetchone()
            current_revision = int(current["draft_revision"]) if current else 0
            if current_revision != expected_revision:
                raise MapDraftRevisionConflict
            existing = (
                {"payload": _json(current["payload"])} if current is not None else None
            )
            payload = _normalize_map_payload(
                map_name, _public_draft_payload(map_name, draft), existing
            )
            next_revision = (
                int(revision_override)
                if revision_override is not None
                else current_revision + 1
            )
            waypoint_count = len(payload.get("waypoints", []))
            if current is None:
                cursor.execute(
                    """
                    INSERT INTO map_projects
                      (map_name, format_version, payload, waypoint_count,
                       lane_count, draft_revision)
                    VALUES (%s, %s, %s, %s, 0, %s)
                    """,
                    (
                        map_name,
                        draft["format_version"],
                        json.dumps(payload, ensure_ascii=False),
                        waypoint_count,
                        next_revision,
                    ),
                )
                project_id = int(cursor.lastrowid)
            else:
                project_id = int(current["project_id"])
                cursor.execute(
                    """
                    UPDATE map_projects
                    SET format_version = %s, payload = %s,
                        drawing_name = NULL, drawing_extension = NULL,
                        drawing_bytes = NULL, drawing_width = NULL,
                        drawing_height = NULL, building_yaml = NULL,
                        building_yaml_name = NULL, waypoint_count = %s,
                        lane_count = 0, draft_revision = %s
                    WHERE project_id = %s
                    """,
                    (
                        draft["format_version"],
                        json.dumps(payload, ensure_ascii=False),
                        waypoint_count,
                        next_revision,
                        project_id,
                    ),
                )

            cursor.execute(
                "DELETE FROM map_project_robots WHERE project_id = %s",
                (project_id,),
            )
            cursor.execute(
                "DELETE FROM map_project_waypoints WHERE project_id = %s",
                (project_id,),
            )
            cursor.execute(
                "DELETE FROM map_project_files WHERE project_id = %s",
                (project_id,),
            )
            cursor.execute(
                "DELETE FROM map_project_fleets WHERE project_id = %s",
                (project_id,),
            )
            for seq, waypoint in enumerate(payload.get("waypoints", []), start=1):
                point = waypoint["point"]
                map_pose = waypoint.get("mapPose") or []
                cursor.execute(
                    """
                    INSERT INTO map_project_waypoints
                      (waypoint_uuid, project_id, seq, location_code,
                       rmf_waypoint_name, category, x, y, yaw,
                       map_x, map_y, map_yaw, active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, 1)
                    """,
                    (
                        waypoint["waypointUuid"],
                        project_id,
                        seq,
                        waypoint.get("locationCode"),
                        waypoint["rmfWaypointName"],
                        waypoint.get("category", "일반"),
                        point[0],
                        point[1],
                        waypoint.get("yaw"),
                        map_pose[0] if len(map_pose) >= 1 else None,
                        map_pose[1] if len(map_pose) >= 2 else None,
                        map_pose[2] if len(map_pose) >= 3 else None,
                    ),
                )

            for stored in prepared_sources:
                cursor.execute(
                    """
                    INSERT INTO map_project_sources
                      (source_uuid, project_id, source_type, file_name, mime_type,
                       content_bytes, sha256, byte_size, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        stored["source_uuid"],
                        project_id,
                        stored["source_type"],
                        stored["file_name"],
                        stored["mime_type"],
                        stored["content_bytes"],
                        stored["sha256"],
                        stored["byte_size"],
                        json.dumps(stored["metadata"], ensure_ascii=False)
                        if stored["metadata"] is not None
                        else None,
                    ),
                )
            for source_type, source_uuid in draft.get("source_uuids", {}).items():
                cursor.execute(
                    """
                    SELECT source_type FROM map_project_sources
                    WHERE project_id = %s AND source_uuid = %s
                    """,
                    (project_id, source_uuid),
                )
                source = cursor.fetchone()
                if source is None or source["source_type"] != source_type:
                    raise MapProjectSourceValidationError(
                        "source UUID is absent, cross-project, or has the wrong type"
                    )
            saved = self._load_map_project(connection, map_name)
            if saved is None:
                raise MapProjectNotFound
            return saved
        finally:
            cursor.close()

    def save_public_map_draft(
        self,
        map_name: str,
        draft: dict[str, Any],
        expected_revision: int,
        staged_sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        with self.database.connection() as connection:
            try:
                saved = self._save_public_map_draft_on_connection(
                    connection,
                    map_name,
                    draft,
                    expected_revision,
                    staged_sources,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return _public_draft_from_project(saved)

    def delete_public_map_draft(self, map_name: str) -> None:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    SELECT project_id, draft_revision FROM map_projects
                    WHERE map_name = %s FOR UPDATE
                    """,
                    (map_name,),
                )
                project = cursor.fetchone()
                if project is None:
                    raise MapProjectNotFound
                cursor.execute(
                    """
                    SELECT draft_revision, manifest FROM map_revisions
                    WHERE map_name = %s AND state = 'published'
                    ORDER BY published_at DESC LIMIT 1 FOR UPDATE
                    """,
                    (map_name,),
                )
                active = cursor.fetchone()
                if active is None:
                    cursor.execute(
                        "DELETE FROM map_projects WHERE project_id = %s",
                        (project["project_id"],),
                    )
                    connection.commit()
                    return
                manifest = _json(active["manifest"])
                snapshot = manifest.get("draft_snapshot")
                if not isinstance(snapshot, dict):
                    raise PublishedMapProjectDeleteConflict
                self._save_public_map_draft_on_connection(
                    connection,
                    map_name,
                    snapshot,
                    int(project["draft_revision"]),
                    [],
                    revision_override=int(active["draft_revision"]),
                )
                referenced = list(snapshot.get("source_uuids", {}).values())
                if referenced:
                    placeholders = ",".join(["%s"] * len(referenced))
                    cursor.execute(
                        f"""
                        DELETE FROM map_project_sources
                        WHERE project_id = %s AND source_uuid NOT IN ({placeholders})
                        """,
                        (project["project_id"], *referenced),
                    )
                else:
                    cursor.execute(
                        "DELETE FROM map_project_sources WHERE project_id = %s",
                        (project["project_id"],),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def active_revision(self, map_name: str) -> str | None:
        publication = self.get_published_map(map_name)
        return str(publication["map_revision"]) if publication else None

    def deployment_failure_events(self, map_name: str) -> list[dict[str, Any]]:
        return [
            row
            for row in self._all(
                """
                SELECT event_id, event_uuid, occurred_at, event_type, payload
                FROM operation_events WHERE event_type = 'MAP_DEPLOYMENT_FAILED'
                ORDER BY event_id
                """
            )
            if (_json(row.get("payload")) or {}).get("map_name") == map_name
        ]

    def store_map_project_source(
        self, map_name: str, source: dict[str, Any]
    ) -> dict[str, Any]:
        """Append one immutable source row; equal bytes in another project stay distinct."""
        stored = _new_map_project_source(source)
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT project_id FROM map_projects WHERE map_name = %s FOR UPDATE",
                    (map_name,),
                )
                project = cursor.fetchone()
                if project is None:
                    raise MapProjectNotFound
                cursor.execute(
                    """
                    INSERT INTO map_project_sources
                      (source_uuid, project_id, source_type, file_name, mime_type,
                       content_bytes, sha256, byte_size, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        stored["source_uuid"],
                        project["project_id"],
                        stored["source_type"],
                        stored["file_name"],
                        stored["mime_type"],
                        stored["content_bytes"],
                        stored["sha256"],
                        stored["byte_size"],
                        json.dumps(stored["metadata"], ensure_ascii=False)
                        if stored["metadata"] is not None
                        else None,
                    ),
                )
                cursor.execute(
                    """
                    SELECT s.source_uuid, p.map_name, s.source_type, s.file_name,
                           s.mime_type, s.content_bytes, s.sha256, s.byte_size,
                           s.metadata, s.created_at
                    FROM map_project_sources s
                    JOIN map_projects p ON p.project_id = s.project_id
                    WHERE s.source_uuid = %s
                    """,
                    (stored["source_uuid"],),
                )
                result = _seoul_datetimes(dict(cursor.fetchone()))
                result["metadata"] = _json(result["metadata"])
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def get_map_project_source(
        self, map_name: str, source_uuid: str
    ) -> dict[str, Any] | None:
        rows = self._all(
            """
            SELECT s.source_uuid, p.map_name, s.source_type, s.file_name,
                   s.mime_type, s.content_bytes, s.sha256, s.byte_size,
                   s.metadata, s.created_at
            FROM map_project_sources s
            JOIN map_projects p ON p.project_id = s.project_id
            WHERE p.map_name = %s AND s.source_uuid = %s
            """,
            (map_name, source_uuid),
        )
        if not rows:
            return None
        rows[0]["metadata"] = _json(rows[0]["metadata"])
        return rows[0]

    def save_map_project(
        self, map_name: str, project: dict[str, Any], expected_revision: int | None
    ) -> dict[str, Any]:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    SELECT project_id, payload, draft_revision
                    FROM map_projects WHERE map_name = %s FOR UPDATE
                    """,
                    (map_name,),
                )
                current = cursor.fetchone()
                current_revision = int(current["draft_revision"]) if current else None
                if expected_revision is not None and expected_revision != current_revision:
                    raise MapDraftRevisionConflict
                existing = (
                    {"payload": _json(current["payload"])} if current is not None else None
                )
                payload = _normalize_map_payload(map_name, project["payload"], existing)
                drawing = payload.get("drawing") or {}
                drawing_bytes = drawing.get("bytes")
                decoded_drawing = (
                    base64.b64decode(drawing_bytes) if isinstance(drawing_bytes, str) else None
                )
                waypoint_count = len(payload.get("waypoints", []))
                if current is None:
                    cursor.execute(
                        """
                        INSERT INTO map_projects
                          (map_name, format_version, payload, drawing_name,
                           drawing_extension, drawing_bytes, drawing_width,
                           drawing_height, building_yaml, building_yaml_name,
                           waypoint_count, draft_revision)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, 1)
                        """,
                        (
                            map_name, project["format_version"],
                            json.dumps(payload, ensure_ascii=False), drawing.get("name"),
                            drawing.get("extension"), decoded_drawing,
                            drawing.get("pixelWidth"), drawing.get("pixelHeight"),
                            project.get("building_yaml"),
                            project.get("building_yaml_name"), waypoint_count,
                        ),
                    )
                    project_id = int(cursor.lastrowid)
                else:
                    project_id = int(current["project_id"])
                    cursor.execute(
                        """
                        UPDATE map_projects
                        SET format_version = %s, payload = %s, drawing_name = %s,
                            drawing_extension = %s, drawing_bytes = %s,
                            drawing_width = %s, drawing_height = %s,
                            building_yaml = %s, building_yaml_name = %s,
                            waypoint_count = %s,
                            draft_revision = draft_revision + 1
                        WHERE project_id = %s
                        """,
                        (
                            project["format_version"],
                            json.dumps(payload, ensure_ascii=False), drawing.get("name"),
                            drawing.get("extension"), decoded_drawing,
                            drawing.get("pixelWidth"), drawing.get("pixelHeight"),
                            project.get("building_yaml"),
                            project.get("building_yaml_name"), waypoint_count,
                            project_id,
                        ),
                    )
                cursor.execute("DELETE FROM map_project_robots WHERE project_id = %s", (project_id,))
                cursor.execute("DELETE FROM map_project_waypoints WHERE project_id = %s", (project_id,))
                waypoint_by_name: dict[str, str] = {}
                for seq, waypoint in enumerate(payload.get("waypoints", []), start=1):
                    name = waypoint.get("rmfWaypointName") or waypoint.get("name", "")
                    waypoint_by_name[name] = waypoint["waypointUuid"]
                    point = waypoint["point"]
                    cursor.execute(
                        """
                        INSERT INTO map_project_waypoints
                          (waypoint_uuid, project_id, seq, location_code,
                           rmf_waypoint_name, category, x, y, yaw,
                           map_x, map_y, map_yaw, active)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, 1)
                        """,
                        (
                            waypoint["waypointUuid"], project_id, seq,
                            waypoint.get("locationCode"), name,
                            waypoint.get("category", "일반"), point[0], point[1],
                            waypoint.get("yaw"),
                            (waypoint.get("mapPose") or [None, None])[0],
                            (waypoint.get("mapPose") or [None, None])[1],
                            (waypoint.get("mapPose") or [None, None, None])[2]
                            if len(waypoint.get("mapPose") or []) >= 3 else None,
                        ),
                    )
                cursor.execute("DELETE FROM map_project_files WHERE project_id = %s", (project_id,))
                for file in project.get("files", []):
                    cursor.execute(
                        """
                        INSERT INTO map_project_files
                          (project_id, file_name, kind, description, executable, content)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            project_id, file["file_name"], file["kind"],
                            file.get("description", ""), bool(file.get("executable")),
                            file["content"],
                        ),
                    )
                cursor.execute("DELETE FROM map_project_fleets WHERE project_id = %s", (project_id,))
                fleet = project.get("fleet")
                if fleet:
                    cursor.execute(
                        """
                        INSERT INTO map_project_fleets (project_id, fleet_name, settings)
                        VALUES (%s, %s, %s)
                        """,
                        (project_id, fleet["fleet_name"], json.dumps(fleet["settings"], ensure_ascii=False)),
                    )
                for robot in project.get("robots", []):
                    cursor.execute(
                        """
                        INSERT INTO map_project_robots
                          (project_id, robot_id, seq, display_name, model, kind,
                           data_source, gz_name, zones, charger_waypoint_uuid,
                           spawn_x, spawn_y, spawn_heading)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s)
                        """,
                        (
                            project_id, robot["robot_id"], robot["seq"],
                            robot["display_name"], robot["model"], robot["kind"],
                            robot["data_source"], robot["gz_name"],
                            json.dumps(robot.get("zones", []), ensure_ascii=False),
                            waypoint_by_name.get(robot.get("charger_waypoint_name")),
                            robot.get("spawn_x"), robot.get("spawn_y"),
                            robot.get("spawn_heading", 0.0),
                        ),
                    )
                saved = self._load_map_project(connection, map_name)
                if saved is None:
                    raise MapProjectNotFound
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
        return saved

    def delete_map_project(self, map_name: str) -> None:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT project_id FROM map_projects WHERE map_name = %s FOR UPDATE",
                    (map_name,),
                )
                project = cursor.fetchone()
                if project is None:
                    raise MapProjectNotFound
                cursor.execute(
                    "SELECT 1 FROM map_revisions WHERE source_project_id = %s LIMIT 1",
                    (project["project_id"],),
                )
                if cursor.fetchone() is not None:
                    raise PublishedMapProjectDeleteConflict
                cursor.execute(
                    "DELETE FROM map_projects WHERE project_id = %s",
                    (project["project_id"],),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def validate_map_project(self, map_name: str) -> dict[str, Any]:
        project = self.get_map_project(map_name)
        if project is None:
            raise MapProjectNotFound
        errors = _validate_map_draft(project)
        return {"valid": not errors, "errors": errors}

    @staticmethod
    def _location_type(category: str) -> str:
        return {
            "대기": "staging", "주차": "staging", "홈": "staging",
            "충전": "charger", "픽업": "inbound_dock",
            "드랍오프": "outbound_dock", "설비": "workstation",
            "일반": "waypoint",
        }[category]

    def publish_map_project(
        self, map_name: str, publication: dict[str, Any]
    ) -> dict[str, Any]:
        if not publication["map_revision"].startswith(f"{map_name}:"):
            raise MapRevisionContentConflict
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    SELECT project_id, payload, draft_revision
                    FROM map_projects WHERE map_name = %s FOR UPDATE
                    """,
                    (map_name,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise MapProjectNotFound
                project_id = int(row["project_id"])
                project = self._load_map_project(connection, map_name)
                if project is None:
                    raise MapProjectNotFound
                errors = _validate_map_draft(project)
                if errors:
                    raise MapProjectValidationError(errors)
                cursor.execute(
                    "SELECT * FROM map_revisions WHERE map_revision = %s",
                    (publication["map_revision"],),
                )
                existing = cursor.fetchone()
                if existing:
                    immutable_identity = {
                        "map_name": map_name,
                        "source_project_id": project_id,
                        "draft_revision": int(row["draft_revision"]),
                        "building_sha256": publication["building_sha256"],
                        "nav_graph_sha256": publication["nav_graph_sha256"],
                        "world_sha256": publication["world_sha256"],
                        "manifest": publication.get("manifest", {}),
                        "published_by": publication["published_by"],
                    }
                    existing_identity = {
                        **{key: existing[key] for key in immutable_identity if key != "manifest"},
                        "manifest": _json(existing["manifest"]),
                    }
                    if existing_identity != immutable_identity:
                        raise MapRevisionContentConflict
                    connection.rollback()
                    result = dict(existing)
                    result["manifest"] = _json(result["manifest"])
                    return _seoul_datetimes(result)
                errors = _validate_publication_artifacts(project, publication)
                if errors:
                    raise MapProjectValidationError(errors)
                cursor.execute(
                    "UPDATE map_revisions SET state = 'retired' WHERE map_name = %s AND state = 'published'",
                    (map_name,),
                )
                cursor.execute(
                    """
                    INSERT INTO map_revisions
                      (map_revision, map_name, source_project_id, draft_revision,
                       state, building_sha256, nav_graph_sha256, world_sha256,
                       manifest, published_by)
                    VALUES (%s, %s, %s, %s, 'published', %s, %s, %s, %s, %s)
                    """,
                    (
                        publication["map_revision"], map_name, project_id,
                        row["draft_revision"], publication["building_sha256"],
                        publication["nav_graph_sha256"], publication["world_sha256"],
                        json.dumps(publication.get("manifest", {}), ensure_ascii=False),
                        publication["published_by"],
                    ),
                )
                active_codes: list[str] = []
                for waypoint in project["payload"].get("waypoints", []):
                    location_code = waypoint.get("locationCode")
                    if not location_code:
                        continue
                    active_codes.append(location_code)
                    map_pose = waypoint["mapPose"]
                    metadata = json.dumps(
                        {
                            "authoring_managed": True,
                            "active": True,
                            "waypoint_uuid": waypoint["waypointUuid"],
                            "map_revision": publication["map_revision"],
                        },
                        ensure_ascii=False,
                    )
                    location_type = self._location_type(waypoint.get("category", "일반"))
                    name = waypoint.get("name") or waypoint["rmfWaypointName"]
                    cursor.execute(
                        "SELECT location_type, map_name, metadata FROM locations WHERE location_code = %s",
                        (location_code,),
                    )
                    existing_location = cursor.fetchone()
                    existing_metadata = (
                        _json(existing_location["metadata"])
                        if existing_location else {}
                    ) or {}
                    if (
                        existing_location
                        and existing_metadata.get("authoring_managed") is True
                        and existing_location["map_name"] != map_name
                    ):
                        raise MapProjectValidationError(
                            [f"{location_code}: 다른 published map이 소유합니다"]
                        )
                    if waypoint.get("category") == "픽업" and existing_location:
                        location_type = existing_location["location_type"]
                    cursor.execute(
                        """
                        INSERT INTO locations
                          (location_code, name, location_type, map_name,
                           rmf_waypoint_name, pose_x, pose_y, pose_yaw, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                          name = %s, location_type = %s, map_name = %s,
                          rmf_waypoint_name = %s, pose_x = %s, pose_y = %s,
                          pose_yaw = %s, metadata = %s
                        """,
                        (
                            location_code, name, location_type, map_name,
                            waypoint["rmfWaypointName"], map_pose[0], map_pose[1],
                            map_pose[2] if len(map_pose) >= 3 else None, metadata,
                            name, location_type, map_name, waypoint["rmfWaypointName"],
                            map_pose[0], map_pose[1],
                            map_pose[2] if len(map_pose) >= 3 else None, metadata,
                        ),
                    )
                for public_feature in project["payload"].get(
                    "publicFeatures", []
                ):
                    feature = _public_feature_projection(
                        map_name, publication["map_revision"], public_feature
                    )
                    if feature["feature_type"] == "fiducial":
                        cursor.execute(
                            "SELECT location_id FROM locations WHERE location_code = %s",
                            (feature["properties"]["target_location_code"],),
                        )
                        target = cursor.fetchone()
                        feature["location_id"] = (
                            int(target["location_id"]) if target else None
                        )
                    cursor.execute(
                        """
                        INSERT INTO map_features
                          (map_name, map_revision, feature_code, feature_type,
                           location_id, marker_code, geometry, properties, active)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
                        """,
                        (
                            feature["map_name"],
                            feature["map_revision"],
                            feature["feature_code"],
                            feature["feature_type"],
                            feature["location_id"],
                            feature["marker_code"],
                            json.dumps(feature["geometry"], ensure_ascii=False),
                            json.dumps(feature["properties"], ensure_ascii=False),
                        ),
                    )
                if active_codes:
                    placeholders = ",".join(["%s"] * len(active_codes))
                    cursor.execute(
                        f"""
                        UPDATE locations
                        SET metadata = JSON_SET(COALESCE(metadata, JSON_OBJECT()),
                          '$.active', false,
                          '$.retired_map_revision', %s)
                        WHERE map_name = %s
                          AND JSON_EXTRACT(metadata, '$.authoring_managed') = true
                          AND location_code NOT IN ({placeholders})
                        """,
                        (publication["map_revision"], map_name, *active_codes),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE locations
                        SET metadata = JSON_SET(COALESCE(metadata, JSON_OBJECT()),
                          '$.active', false,
                          '$.retired_map_revision', %s)
                        WHERE map_name = %s
                          AND JSON_EXTRACT(metadata, '$.authoring_managed') = true
                        """,
                        (publication["map_revision"], map_name),
                    )
                cursor.execute(
                    """
                    SELECT r.*, w.location_code AS home_location_code
                    FROM map_project_robots r
                    LEFT JOIN map_project_waypoints w
                      ON w.waypoint_uuid = r.charger_waypoint_uuid
                    WHERE r.project_id = %s ORDER BY r.seq
                    """,
                    (project_id,),
                )
                for robot in cursor.fetchall():
                    mobile = robot["kind"] == "mobile"
                    capabilities = (
                        {"navigation": True, "rmf": True, "rmf_robot_name": robot["robot_id"]}
                        if mobile else {"pick": True, "place": True}
                    )
                    device_type = "mobile" if mobile else "arm"
                    fleet_name = None
                    if mobile:
                        cursor.execute(
                            "SELECT fleet_name FROM map_project_fleets WHERE project_id = %s",
                            (project_id,),
                        )
                        fleet_row = cursor.fetchone()
                        fleet_name = fleet_row["fleet_name"] if fleet_row else None
                    cursor.execute(
                        "SELECT location_id FROM locations WHERE location_code = %s",
                        (robot["home_location_code"],),
                    )
                    home = cursor.fetchone()
                    home_location_id = home["location_id"] if home else None
                    cursor.execute(
                        """
                        INSERT INTO devices
                          (device_id, device_type, name, model, fleet_name,
                           home_location_id, capabilities)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                          device_type = %s, name = %s, model = %s,
                          fleet_name = %s, home_location_id = %s,
                          capabilities = JSON_MERGE_PATCH(
                            COALESCE(capabilities, JSON_OBJECT()), %s)
                        """,
                        (
                            robot["robot_id"], device_type, robot["display_name"],
                            robot["model"], fleet_name, home_location_id,
                            json.dumps(capabilities, ensure_ascii=False),
                            device_type, robot["display_name"], robot["model"],
                            fleet_name, home_location_id,
                            json.dumps(
                                {"rmf_robot_name": robot["robot_id"]} if mobile else {},
                                ensure_ascii=False,
                            ),
                        ),
                    )
                cursor.execute(
                    """
                    SELECT map_revision, map_name, draft_revision, state,
                           building_sha256, nav_graph_sha256, world_sha256,
                           manifest, published_by, published_at
                    FROM map_revisions WHERE map_revision = %s
                    """,
                    (publication["map_revision"],),
                )
                result = dict(cursor.fetchone())
                result["manifest"] = _json(result["manifest"])
                result = _seoul_datetimes(result)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
        return result

    def get_published_map(self, map_name: str) -> dict[str, Any] | None:
        rows = self._all(
            """
            SELECT map_revision, map_name, draft_revision, state,
                   building_sha256, nav_graph_sha256, world_sha256,
                   manifest, published_by, published_at
            FROM map_revisions
            WHERE map_name = %s AND state = 'published'
            ORDER BY published_at DESC LIMIT 1
            """,
            (map_name,),
        )
        if not rows:
            return None
        rows[0]["manifest"] = _json(rows[0]["manifest"])
        return rows[0]

    def list_projected_map_features(
        self, map_revision: str
    ) -> list[dict[str, Any]]:
        rows = self._all(
            """
            SELECT map_name, map_revision, feature_code, feature_type,
                   location_id, marker_code, geometry, properties, active
            FROM map_features WHERE map_revision = %s ORDER BY feature_id
            """,
            (map_revision,),
        )
        for row in rows:
            row["geometry"] = _json(row["geometry"])
            row["properties"] = _json(row["properties"])
            row["active"] = bool(row["active"])
        return rows

    @staticmethod
    def _project_robot_state(status: dict[str, Any]) -> tuple[str, str]:
        if status["safety_state"] != 0:
            return "estop", "safety_hold"
        if not status["telemetry_valid"]:
            return "error", "fault"
        if not status["execution_ready"]:
            return "blocked", "warning"
        if status["navigation_state"] == 1:
            return "moving", "ok"
        return "idle", "ok"

    def ingest_robot_status(self, status: dict[str, Any]) -> None:
        state, health = self._project_robot_state(status)
        context = status["task_context"]
        details = {
            "session_id": status["session_id"],
            "sequence": status["sequence"],
            "sent_at_ns": status["sent_at_ns"],
            "map_revision": status["map_revision"],
            "frame_id": status["frame_id"],
            "twist": status["twist"],
            "navigation_state": status["navigation_state"],
            "task_progress": status["task_progress"],
            "battery_condition": status["battery_condition"],
            "battery_policy": status["battery_policy"],
            "safety_state": status["safety_state"],
            "cargo_state": status["cargo_state"],
            "telemetry_valid": status["telemetry_valid"],
            "execution_ready": status["execution_ready"],
            "dispatchable": status["dispatchable"],
            "errors": status["errors"],
            "task_context": context,
        }
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT details FROM device_states WHERE device_id = %s FOR UPDATE",
                    (status["robot_id"],),
                )
                existing = cursor.fetchone()
                if existing:
                    previous = _json(existing["details"]) or {}
                    if (
                        previous.get("session_id") == status["session_id"]
                        and int(previous.get("sequence", 0)) >= status["sequence"]
                    ):
                        raise RuntimeContextConflict
                cursor.execute(
                    """
                    INSERT INTO device_states
                      (device_id, observed_at, state, health, current_job_step_id,
                       pose_x, pose_y, pose_yaw, battery_pct, progress, details)
                    VALUES (%s, NOW(6), %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                      observed_at=VALUES(observed_at), state=VALUES(state),
                      health=VALUES(health), current_job_step_id=VALUES(current_job_step_id),
                      pose_x=VALUES(pose_x), pose_y=VALUES(pose_y), pose_yaw=VALUES(pose_yaw),
                      battery_pct=VALUES(battery_pct), progress=VALUES(progress), details=VALUES(details)
                    """,
                    (
                        status["robot_id"], state, health,
                        context["job_step_id"] if context["active"] else None,
                        status["pose"]["x"], status["pose"]["y"], status["pose"]["yaw"],
                        status["battery_percentage"], status["task_progress"],
                        json.dumps(details, ensure_ascii=False),
                    ),
                )
                connection.commit()
            finally:
                cursor.close()

    def ingest_task_event(self, event: dict[str, Any]) -> dict[str, Any]:
        from .outcomes import OutcomeClassifier

        context = event["task_context"]
        event_uuid = event["event_id"]
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT event_id, event_type, payload FROM operation_events WHERE event_uuid = %s",
                    (event_uuid,),
                )
                existing = cursor.fetchone()
                if existing:
                    existing_payload = _json(existing["payload"]) or {}
                    if existing_payload.get("wire_event") != event:
                        raise RuntimeContextConflict
                    return {"event_id": int(existing["event_id"]), "event_type": existing["event_type"]}
                cursor.execute(
                    """
                    SELECT js.job_id, js.job_step_id, js.assignment_revision,
                           js.assigned_device_id, js.rmf_task_id, js.state,
                           attempt.attempt_uuid, attempt.state AS attempt_state,
                           attempt.parameters AS attempt_parameters
                    FROM job_steps js
                    LEFT JOIN job_step_attempts attempt
                      ON attempt.job_step_id = js.job_step_id
                     AND attempt.assignment_revision = js.assignment_revision
                     AND attempt.command_uuid = %s
                    WHERE js.job_step_id = %s
                    FOR UPDATE
                    """,
                    (context["command_id"], context["job_step_id"]),
                )
                step = cursor.fetchone()
                attempt_parameters = _json(step.get("attempt_parameters")) if step else {}
                if step is None or any(
                    (
                        int(step["job_id"]) != context["job_id"],
                        int(step["assignment_revision"]) != context["assignment_revision"],
                        step["assigned_device_id"] != event["robot_id"],
                        step["rmf_task_id"] != context["rmf_task_id"],
                        step.get("attempt_uuid") is None,
                        (attempt_parameters or {}).get("map_revision")
                        != context["map_revision"],
                    )
                ):
                    raise RuntimeContextConflict
                terminal_states = {"succeeded", "failed", "cancelled"}
                if step["state"] in terminal_states:
                    raise RuntimeContextConflict
                if event["event_type"] == "started":
                    if step["state"] not in {"pending", "running"} or step["attempt_state"] not in {"created", "running"}:
                        raise RuntimeContextConflict
                elif event["event_type"] == "arrived":
                    if step["state"] != "running" or step["attempt_state"] != "running":
                        raise RuntimeContextConflict
                elif not (
                    (step["state"] == "pending" and step["attempt_state"] == "created")
                    or (step["state"] == "running" and step["attempt_state"] == "running")
                ):
                    raise RuntimeContextConflict
                if event["event_type"] != "started":
                    cursor.execute(
                        """
                        SELECT observed_at, details,
                               TIMESTAMPDIFF(MICROSECOND, observed_at, NOW(6)) AS age_us
                        FROM device_states WHERE device_id = %s FOR UPDATE
                        """,
                        (event["robot_id"],),
                    )
                    status = cursor.fetchone()
                    status_details = _json(status["details"]) if status else {}
                    if (
                        status is None
                        or int(status["age_us"]) < 0
                        or int(status["age_us"]) > 2_000_000
                        or status_details.get("session_id") != event.get("session_id")
                        or status_details.get("map_revision") != context["map_revision"]
                        or status_details.get("task_context") != context
                    ):
                        raise RuntimeContextConflict
                transition = {
                    "started": ("running", "navigation.segment.started"),
                    "arrived": ("succeeded", "navigation.waypoint.arrived"),
                    "canceled": ("cancelled", "navigation.segment.cancelled"),
                    "failed": ("failed", "navigation.segment.failed"),
                }[event["event_type"]]
                terminal = event["event_type"] != "started"
                facts = {
                    "data_complete": True,
                    "success_reason": event["reason_code"] if event["event_type"] == "arrived" else None,
                    "navigation_reason": event["reason_code"] if event["event_type"] in {"failed", "canceled"} else None,
                }
                if event["event_type"] == "arrived":
                    twist = status_details.get("twist", {})
                    if status_details.get("telemetry_valid") is not True:
                        facts["telemetry_reason"] = "SENSOR_TELEMETRY_STALE"
                    elif status_details.get("safety_state") != 0:
                        facts["safety_reason"] = "SAFETY_LATCHED"
                    elif status_details.get("navigation_state") != 2:
                        facts["criteria_reason"] = "GOAL_TOLERANCE_NOT_MET"
                    elif (
                        abs(float(twist.get("linear_x_mps", 0.0))) > 0.02
                        or abs(float(twist.get("angular_z_rps", 0.0))) > 0.05
                    ):
                        facts["criteria_reason"] = "ROBOT_NOT_STOPPED"
                classified = OutcomeClassifier().classify(facts)
                arrived_succeeded = (
                    event["event_type"] == "arrived"
                    and classified.failure_domain == "none"
                )
                if event["event_type"] == "started":
                    cursor.execute(
                        """
                        UPDATE job_step_attempts
                        SET state = 'running', started_at = COALESCE(started_at, NOW(6))
                        WHERE job_step_id = %s AND command_uuid = %s
                          AND assignment_revision = %s
                        """,
                        (step["job_step_id"], context["command_id"], context["assignment_revision"]),
                    )
                else:
                    outcome = {
                        "arrived": "succeeded" if arrived_succeeded else "failed",
                        "canceled": "cancelled",
                        "failed": "failed",
                    }[event["event_type"]]
                    cursor.execute(
                        """
                        UPDATE job_step_attempts
                        SET state = 'finished', outcome = %s, success = %s,
                            outcome_reason_code = %s, failure_domain = %s,
                            detail = %s, completed_at = NOW(6),
                            policy_name = 'outcome-classifier', policy_version = %s,
                            started_at = COALESCE(started_at, created_at)
                        WHERE job_step_id = %s AND command_uuid = %s
                          AND assignment_revision = %s
                        """,
                        (
                            outcome,
                            arrived_succeeded,
                            classified.primary_reason,
                            classified.failure_domain,
                            event.get("detail"),
                            classified.catalog_version,
                            step["job_step_id"],
                            context["command_id"],
                            context["assignment_revision"],
                        ),
                    )
                if cursor.rowcount != 1:
                    raise RuntimeContextConflict
                cursor.execute(
                    """
                    UPDATE job_steps SET state = %s,
                      final_outcome_reason_code = CASE WHEN %s THEN %s ELSE final_outcome_reason_code END,
                      final_method_code = CASE WHEN %s THEN %s ELSE final_method_code END,
                      started_at = CASE WHEN %s = 'running' THEN COALESCE(started_at, NOW(6)) ELSE started_at END,
                      completed_at = CASE WHEN %s THEN NOW(6) ELSE completed_at END
                    WHERE job_step_id = %s
                    """,
                    (
                        "failed" if event["event_type"] == "arrived" and not arrived_succeeded else transition[0],
                        terminal, classified.primary_reason, terminal,
                        event["method_code"],
                        "failed" if event["event_type"] == "arrived" and not arrived_succeeded else transition[0],
                        terminal, step["job_step_id"],
                    ),
                )
                payload = {
                    "primary_reason": classified.primary_reason,
                    "failure_domain": classified.failure_domain,
                    "contributing_reasons": list(classified.contributing_reasons),
                    "classifier_version": classified.catalog_version,
                    "wire_event": event,
                }
                cursor.execute(
                    """
                    INSERT INTO operation_events
                      (event_uuid, occurred_at, device_id, job_id, job_step_id,
                       severity, category, event_type, message, payload)
                    VALUES (%s, NOW(6), %s, %s, %s, %s, 'operation', %s, %s, %s)
                    """,
                    (
                        event_uuid, event["robot_id"], step["job_id"], step["job_step_id"],
                        "warning" if event["event_type"] == "failed" else "info",
                        transition[1], event.get("detail"), json.dumps(payload, ensure_ascii=False),
                    ),
                )
                result = {"event_id": int(cursor.lastrowid), "event_type": transition[1]}
                connection.commit()
                return result
            finally:
                cursor.close()

    def list_inventory(self) -> list[dict[str, object]]:
        return self._all(
            """
            SELECT lot.lot_id, lot.lot_code, lot.product_code, lot.item_name,
                   lot.temperature_zone, loc.location_code, lot.expiry_date,
                   lot.available_qty, lot.reserved_qty, lot.state
            FROM inventory_lots lot
            LEFT JOIN locations loc ON loc.location_id = lot.location_id
            ORDER BY lot.expiry_date, lot.lot_id
            """
        )

    @staticmethod
    def _lot(cursor, lot_id: int, *, for_update: bool = False):
        lock = " FOR UPDATE" if for_update else ""
        cursor.execute(
            """
            SELECT lot.lot_id, lot.lot_code, lot.product_code, lot.item_name,
                   lot.temperature_zone, loc.location_code, lot.expiry_date,
                   lot.available_qty, lot.reserved_qty, lot.state
            FROM inventory_lots lot
            LEFT JOIN locations loc ON loc.location_id = lot.location_id
            WHERE lot.lot_id = %s
            """ + lock,
            (lot_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def adjust_inventory(
        self,
        lot_id: int,
        quantity_delta: int,
        recorded_by: str,
        note: str | None,
        idempotency_key: str,
    ) -> dict[str, object]:
        event_uuid = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"trihouse:inventory-adjust:{idempotency_key}")
        )
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT payload FROM operation_events WHERE event_uuid = %s",
                    (event_uuid,),
                )
                existing = cursor.fetchone()
                if existing:
                    payload = existing["payload"]
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    expected = {
                        "lot_id": lot_id,
                        "quantity_delta": quantity_delta,
                        "recorded_by": recorded_by,
                    }
                    if any(payload.get(key) != value for key, value in expected.items()):
                        raise IdempotencyConflict
                    lot = self._lot(cursor, lot_id)
                    if lot is None:
                        raise InventoryLotNotFound
                    lot["available_qty"] = payload["quantity_after"]
                    return lot

                lot = self._lot(cursor, lot_id, for_update=True)
                if lot is None:
                    raise InventoryLotNotFound
                quantity_after = int(lot["available_qty"]) + quantity_delta
                if quantity_after < int(lot["reserved_qty"]):
                    raise InventoryQuantityConflict

                cursor.execute(
                    "UPDATE inventory_lots SET available_qty = %s WHERE lot_id = %s",
                    (quantity_after, lot_id),
                )
                cursor.execute(
                    """
                    INSERT INTO inventory_moves
                      (lot_id, move_type, quantity_delta, quantity_after,
                       reserved_delta, reserved_after, recorded_by, note)
                    VALUES (%s, 'adjustment', %s, %s, 0, %s, %s, %s)
                    """,
                    (
                        lot_id,
                        quantity_delta,
                        quantity_after,
                        lot["reserved_qty"],
                        recorded_by,
                        note,
                    ),
                )
                payload = {
                    "idempotency_key": idempotency_key,
                    "lot_id": lot_id,
                    "quantity_delta": quantity_delta,
                    "quantity_after": quantity_after,
                    "recorded_by": recorded_by,
                }
                cursor.execute(
                    """
                    INSERT INTO operation_events
                      (event_uuid, occurred_at, actor_worker_id, severity,
                       category, event_type, message, payload)
                    VALUES (%s, NOW(6), %s, 'info', 'inventory',
                            'inventory.adjusted', %s, %s)
                    """,
                    (
                        event_uuid,
                        recorded_by,
                        note or "inventory quantity adjusted",
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )
                connection.commit()
                lot["available_qty"] = quantity_after
                return lot
            finally:
                cursor.close()

    def list_jobs(self) -> list[dict[str, object]]:
        return self._all(
            """
            SELECT j.job_id, j.job_code, j.operation_type, j.priority, j.state,
                   j.due_at, j.assigned_mobile_id,
                   COUNT(DISTINCT ji.job_item_id) AS item_count,
                   COUNT(DISTINCT js.job_step_id) AS step_count
            FROM jobs j
            LEFT JOIN job_items ji ON ji.job_id = j.job_id
            LEFT JOIN job_steps js ON js.job_id = j.job_id
            GROUP BY j.job_id
            ORDER BY j.priority_rank, j.due_at, j.created_at
            """
        )

    def create_job(self, job: dict[str, Any]) -> dict[str, Any]:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    INSERT INTO jobs
                      (job_code, operation_type, priority, requested_by,
                       external_reference, source_location_id,
                       destination_location_id, due_at, context)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        job["job_code"],
                        job["operation_type"],
                        job["priority"],
                        job.get("requested_by"),
                        job.get("external_reference"),
                        job.get("source_location_id"),
                        job.get("destination_location_id"),
                        _mysql_datetime(job.get("due_at")),
                        json.dumps(job.get("context", {}), ensure_ascii=False),
                    ),
                )
                job_id = int(cursor.lastrowid)
                created_steps = []
                for step in job["steps"]:
                    cursor.execute(
                        """
                        INSERT INTO job_steps
                          (job_id, step_no, executor_type, action_type,
                           target_location_id, input)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            job_id,
                            step["step_no"],
                            step["executor_type"],
                            step["action_type"],
                            step.get("target_location_id"),
                            json.dumps(step.get("input", {}), ensure_ascii=False),
                        ),
                    )
                    created_steps.append(
                        {
                            "job_step_id": int(cursor.lastrowid),
                            "step_no": step["step_no"],
                            "action_type": step["action_type"],
                            "executor_type": step["executor_type"],
                            "target_location_id": step.get("target_location_id"),
                            "state": "pending",
                        }
                    )
                cursor.execute(
                    """
                    INSERT INTO operation_events
                      (event_uuid, occurred_at, actor_worker_id, job_id,
                       severity, category, event_type, message, payload)
                    VALUES (%s, NOW(6), %s, %s, 'info', 'operation',
                            'job.created', 'outbound job created', %s)
                    """,
                    (
                        str(uuid.uuid4()),
                        job.get("requested_by"),
                        job_id,
                        json.dumps(
                            {"job_code": job["job_code"], "step_count": len(created_steps)},
                            ensure_ascii=False,
                        ),
                    ),
                )
                connection.commit()
                return {
                    "job_id": job_id,
                    "job_code": job["job_code"],
                    "state": "queued",
                    "steps": created_steps,
                }
            finally:
                cursor.close()

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    SELECT job_id, job_code, operation_type, priority, state,
                           requested_by, external_reference, source_location_id,
                           destination_location_id, due_at, context, created_at
                    FROM jobs WHERE job_id = %s
                    """,
                    (job_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                job = _seoul_datetimes(dict(row))
                job["context"] = _json(job.get("context")) or {}
                cursor.execute(
                    """
                    SELECT job_step_id, step_no, executor_type, assigned_device_id,
                           assignment_revision, action_type, target_location_id,
                           state, rmf_task_id, input, result, started_at, completed_at
                    FROM job_steps WHERE job_id = %s ORDER BY step_no
                    """,
                    (job_id,),
                )
                steps = []
                for step_row in cursor.fetchall():
                    step = _seoul_datetimes(dict(step_row))
                    step["input"] = _json(step.get("input")) or {}
                    step["result"] = _json(step.get("result"))
                    steps.append(step)
                job["steps"] = steps
                return job
            finally:
                cursor.close()

    def get_job_timeline(self, job_id: int) -> list[dict[str, Any]] | None:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute("SELECT 1 FROM jobs WHERE job_id = %s", (job_id,))
                if cursor.fetchone() is None:
                    return None
                cursor.execute(
                    """
                    SELECT event_id, event_uuid, occurred_at, job_step_id,
                           severity, category, event_type, message, payload
                    FROM operation_events
                    WHERE job_id = %s
                    ORDER BY occurred_at, event_id
                    """,
                    (job_id,),
                )
                events = []
                for event_row in cursor.fetchall():
                    event = _seoul_datetimes(dict(event_row))
                    event["payload"] = _json(event.get("payload"))
                    events.append(event)
                return events
            finally:
                cursor.close()

    def dispatch_step(
        self, job_step_id: int, request: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    SELECT js.job_step_id, js.job_id, js.step_no, js.executor_type,
                           js.action_type, js.target_location_id, js.state, js.input
                    FROM job_steps js
                    WHERE js.job_step_id = %s
                    FOR UPDATE
                    """,
                    (job_step_id,),
                )
                step = cursor.fetchone()
                if step is None:
                    raise JobStepNotFound
                cursor.execute(
                    """
                    SELECT message_id, channel, message_type, state, payload
                    FROM integration_messages
                    WHERE direction = 'outbound' AND idempotency_key = %s
                    LIMIT 1
                    """,
                    (idempotency_key,),
                )
                existing = cursor.fetchone()
                request_fingerprint = {
                    "job_step_id": job_step_id,
                    "actor": request["actor"],
                    "assigned_device_id": request.get("assigned_device_id"),
                    "retry": request.get("retry", False),
                }
                if existing:
                    payload = _json(existing["payload"])
                    if payload.get("request") != request_fingerprint:
                        raise IdempotencyConflict
                    return self._dispatch_record(existing, step, idempotency_key, payload)
                retry = request.get("retry", False)
                if (not retry and step["state"] != "pending") or (
                    retry and step["state"] != "failed"
                ):
                    raise JobStepNotDispatchable
                cursor.execute(
                    """
                    SELECT COUNT(*) AS blocked
                    FROM job_steps
                    WHERE job_id = %s AND step_no < %s AND state <> 'succeeded'
                    """,
                    (step["job_id"], step["step_no"]),
                )
                if int(cursor.fetchone()["blocked"]):
                    raise JobStepNotDispatchable
                cursor.execute(
                    """
                    SELECT 1 FROM integration_messages
                    WHERE direction = 'outbound' AND job_step_id = %s
                      AND state IN ('pending','sent')
                    LIMIT 1
                    """,
                    (job_step_id,),
                )
                if cursor.fetchone():
                    raise JobStepNotDispatchable
                if retry:
                    cursor.execute(
                        """
                        UPDATE job_steps
                        SET state = 'pending', retry_count = retry_count + 1
                        WHERE job_step_id = %s
                        """,
                        (job_step_id,),
                    )
                channel, message_type = self._dispatch_kind(step["executor_type"])
                message_id = str(uuid.uuid4())
                payload = {
                    "request": request_fingerprint,
                    "job_id": int(step["job_id"]),
                    "job_step_id": job_step_id,
                    "step_no": int(step["step_no"]),
                    "action_type": step["action_type"],
                    "target_location_id": step["target_location_id"],
                    "input": _json(step["input"]) or {},
                }
                cursor.execute(
                    """
                    INSERT INTO integration_messages
                      (message_id, direction, channel, device_id, job_step_id,
                       message_type, idempotency_key, payload)
                    VALUES (%s, 'outbound', %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        message_id,
                        channel,
                        request.get("assigned_device_id"),
                        job_step_id,
                        message_type,
                        idempotency_key,
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO operation_events
                      (event_uuid, occurred_at, job_id, job_step_id, severity,
                       category, event_type, message, payload)
                    VALUES (%s, %s, %s, %s, 'info', %s,
                            'navigation.segment.dispatched',
                            'job step dispatch requested', %s)
                    """,
                    (
                        str(uuid.uuid4()),
                        _mysql_datetime(request.get("occurred_at")) or datetime.now(SEOUL).replace(tzinfo=None),
                        step["job_id"],
                        job_step_id,
                        "rmf" if channel == "rmf" else "omx",
                        json.dumps({"message_id": message_id}, ensure_ascii=False),
                    ),
                )
                connection.commit()
                row = {"message_id": message_id, "channel": channel, "message_type": message_type, "state": "pending"}
                return self._dispatch_record(row, step, idempotency_key, payload)
            finally:
                cursor.close()

    @staticmethod
    def _dispatch_kind(executor_type: str) -> tuple[str, str]:
        return {
            "mobile": ("rmf", "dispatch_task_request"),
            "arm": ("omx", "execute_action"),
            "fms": ("pinky", "execute_fms_action"),
        }[executor_type]

    @staticmethod
    def _dispatch_record(row, step, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "message_id": row["message_id"],
            "idempotency_key": key,
            "job_id": int(step["job_id"]),
            "job_step_id": int(step["job_step_id"]),
            "channel": row["channel"],
            "message_type": row["message_type"],
            "state": row["state"],
            "payload": payload,
        }

    def record_rmf_acceptance(
        self, job_step_id: int, rmf_task_id: str, robot_id: str
    ) -> None:
        with self.database.connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE job_steps
                    SET rmf_task_id = %s, assigned_device_id = %s,
                        assignment_revision = assignment_revision + 1
                    WHERE job_step_id = %s
                    """,
                    (rmf_task_id, robot_id, job_step_id),
                )
                if cursor.rowcount != 1:
                    raise JobStepNotFound
                connection.commit()
            finally:
                cursor.close()

    def claim_rmf_dispatches(self, worker_id: str, limit: int) -> list[dict[str, Any]]:
        del worker_id  # Worker identity is currently audit-only; claim ownership is row state.
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    SELECT im.message_id, im.idempotency_key, js.job_id,
                           im.job_step_id, im.channel, im.message_type,
                           im.state, im.payload, loc.location_code,
                           loc.rmf_waypoint_name,
                           CAST(UNIX_TIMESTAMP(im.created_at) * 1000 AS UNSIGNED)
                             AS request_time_ms
                    FROM integration_messages im
                    JOIN job_steps js ON js.job_step_id = im.job_step_id
                    LEFT JOIN locations loc ON loc.location_id = js.target_location_id
                    WHERE im.direction = 'outbound' AND im.channel = 'rmf'
                      AND im.state = 'pending'
                    ORDER BY im.created_at, im.message_id
                    LIMIT %s FOR UPDATE SKIP LOCKED
                    """,
                    (limit,),
                )
                rows = list(cursor.fetchall())
                if rows:
                    cursor.executemany(
                        """
                        UPDATE integration_messages
                        SET state = 'sent', attempts = attempts + 1, sent_at = NOW(6)
                        WHERE message_id = %s
                        """,
                        [(row["message_id"],) for row in rows],
                    )
                    connection.commit()
                result = []
                for row in rows:
                    row = dict(row)
                    row["state"] = "sent"
                    row["payload"] = _json(row["payload"])
                    row["payload"]["target_waypoint"] = (
                        row["payload"].get("input", {}).get("waypoint")
                        or row.pop("rmf_waypoint_name", None)
                        or row.pop("location_code")
                    )
                    row["payload"]["fleet_name"] = row["payload"].get("input", {}).get("fleet_name")
                    row["payload"]["request_time_ms"] = int(row.pop("request_time_ms"))
                    result.append(row)
                return result
            finally:
                cursor.close()

    def record_rmf_dispatch_acceptance(
        self, message_id: str, acceptance: dict[str, Any]
    ) -> dict[str, Any]:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    SELECT im.message_id, im.job_step_id, im.state,
                           im.external_reference,
                           js.rmf_task_id, js.assigned_device_id
                    FROM integration_messages im
                    JOIN job_steps js ON js.job_step_id = im.job_step_id
                    WHERE im.message_id = %s AND im.direction = 'outbound'
                      AND im.channel = 'rmf' AND im.message_type = 'dispatch_task_request'
                    FOR UPDATE
                    """,
                    (message_id,),
                )
                message = cursor.fetchone()
                if message is None:
                    raise DispatchMessageNotFound
                if message["state"] not in {"sent", "acknowledged", "failed"}:
                    raise JobStepNotDispatchable
                pending_assignment = bool(
                    not acceptance["accepted"] and acceptance.get("rmf_task_id")
                )
                pending_booking_reference = (
                    f"rmf:{acceptance['rmf_task_id']}:pending-assignment"
                    if acceptance.get("rmf_task_id")
                    else None
                )
                if (
                    message["external_reference"] is not None
                    and pending_booking_reference != message["external_reference"]
                ):
                    raise IdempotencyConflict
                target_state = (
                    "acknowledged" if acceptance["accepted"]
                    else "sent" if pending_assignment
                    else "failed"
                )
                if message["state"] in {"acknowledged", "failed"}:
                    if message["state"] != target_state:
                        raise IdempotencyConflict
                    if acceptance["accepted"] and (
                        message["rmf_task_id"] != acceptance["rmf_task_id"]
                        or message["assigned_device_id"]
                        != acceptance["assigned_device_id"]
                    ):
                        raise IdempotencyConflict
                elif acceptance["accepted"]:
                    cursor.execute(
                        """
                        UPDATE job_steps
                        SET rmf_task_id = %s, assigned_device_id = %s,
                            assignment_revision = assignment_revision + 1
                        WHERE job_step_id = %s
                        """,
                        (
                            acceptance["rmf_task_id"],
                            acceptance["assigned_device_id"],
                            message["job_step_id"],
                        ),
                    )
                cursor.execute(
                    """
                    UPDATE integration_messages
                    SET state = %s, acknowledged_at = CASE WHEN %s = 'acknowledged'
                         THEN NOW(6) ELSE acknowledged_at END, last_error = %s
                    WHERE message_id = %s
                    """,
                    (target_state, target_state, acceptance.get("detail"), message_id),
                )
                if pending_assignment:
                    cursor.execute(
                        """
                        UPDATE integration_messages
                        SET external_reference = %s
                        WHERE message_id = %s
                        """,
                        (pending_booking_reference, message_id),
                    )
                connection.commit()
                return {
                    "message_id": message_id,
                    "job_step_id": int(message["job_step_id"]),
                    "state": target_state,
                    "rmf_task_id": (
                        message["rmf_task_id"]
                        if message["state"] == "acknowledged"
                        else acceptance.get("rmf_task_id")
                        if acceptance["accepted"] or pending_assignment
                        else None
                    ),
                }
            finally:
                cursor.close()

    def claim_command(
        self, rmf_task_id: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        external_reference = f"rmf:{rmf_task_id}:execution:{request['execution_id']}"
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    SELECT job_step_id, job_id, assignment_revision,
                           assigned_device_id, state
                    FROM job_steps WHERE rmf_task_id = %s FOR UPDATE
                    """,
                    (rmf_task_id,),
                )
                step = cursor.fetchone()
                if step is None:
                    raise JobStepNotFound
                if step["state"] not in {"pending", "running"}:
                    raise CommandClaimConflict
                cursor.execute(
                    """
                    SELECT payload FROM integration_messages
                    WHERE direction = 'outbound' AND message_type = 'execution_command'
                      AND external_reference = %s
                    LIMIT 1
                    """,
                    (external_reference,),
                )
                existing = cursor.fetchone()
                if existing:
                    payload = _json(existing["payload"])
                    identity = payload["claim_identity"]
                    if identity != request:
                        raise CommandClaimConflict
                    return {"task_context": payload["task_context"]}
                if step["assigned_device_id"] != request["robot_id"]:
                    raise CommandClaimConflict
                command_id = str(uuid.uuid4())
                attempt_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    SELECT COALESCE(MAX(attempt_no), 0) + 1 AS attempt_no
                    FROM job_step_attempts
                    WHERE job_step_id = %s AND assignment_revision = %s
                      AND actor_role = 'pinky'
                    """,
                    (step["job_step_id"], step["assignment_revision"]),
                )
                attempt_no = int(cursor.fetchone()["attempt_no"])
                cursor.execute(
                    """
                    INSERT INTO job_step_attempts
                      (attempt_uuid, job_step_id, assignment_revision, actor_role,
                       actor_device_id, attempt_no, command_uuid, method_code,
                       parameters, policy_source)
                    VALUES (%s, %s, %s, 'pinky', %s, %s, %s,
                            'NAV2_DEFAULT', %s, 'nav2')
                    """,
                    (
                        attempt_id,
                        step["job_step_id"],
                        step["assignment_revision"],
                        request["robot_id"],
                        attempt_no,
                        command_id,
                        json.dumps(
                            {"execution_id": request["execution_id"], "map_revision": request["map_revision"]},
                            ensure_ascii=False,
                        ),
                    ),
                )
                context = {
                    "active": True,
                    "job_id": int(step["job_id"]),
                    "job_step_id": int(step["job_step_id"]),
                    "assignment_revision": int(step["assignment_revision"]),
                    "rmf_task_id": rmf_task_id,
                    "command_id": command_id,
                    "map_revision": request["map_revision"],
                    "command_source": "rmf",
                }
                payload = {"claim_identity": request, "task_context": context}
                cursor.execute(
                    """
                    INSERT INTO integration_messages
                      (message_id, direction, channel, device_id, job_step_id,
                       message_type, idempotency_key, external_reference, payload)
                    VALUES (%s, 'outbound', 'pinky', %s, %s,
                            'execution_command', %s, %s, %s)
                    """,
                    (
                        command_id,
                        request["robot_id"],
                        step["job_step_id"],
                        f"command:{rmf_task_id}:{request['robot_id']}:{request['execution_id']}",
                        external_reference,
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )
                connection.commit()
                return {"task_context": context}
            finally:
                cursor.close()


class InMemoryFmsRepository:
    """Deterministic repository implementation for boundary and service tests."""

    def __init__(self):
        self._jobs: dict[int, dict[str, Any]] = {}
        self._steps: dict[int, dict[str, Any]] = {}
        self._events: dict[int, list[dict[str, Any]]] = {}
        self._dispatches: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        self._claims: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
        self._next_job_id = 1
        self._next_step_id = 1
        self._next_event_id = 1
        self._device_states: dict[str, dict[str, Any]] = {}
        self._task_events: dict[str, dict[str, Any]] = {}
        self._map_projects: dict[str, dict[str, Any]] = {}
        self._map_project_sources: dict[str, dict[str, dict[str, Any]]] = {}
        self._map_publications: dict[str, dict[str, Any]] = {}
        self._map_publications_by_revision: dict[str, dict[str, Any]] = {}
        self._map_features: dict[str, list[dict[str, Any]]] = {}

    def ping(self) -> bool:
        return True

    @staticmethod
    def _map_summary(project: dict[str, Any]) -> dict[str, Any]:
        drawing = project["payload"].get("drawing") or {}
        return {
            "map_name": project["map_name"],
            "drawing_name": drawing.get("name"),
            "format_version": project["format_version"],
            "waypoint_count": len(project["payload"].get("waypoints", [])),
            "lane_count": 0,
            "draft_revision": project["draft_revision"],
            "has_building_yaml": project.get("building_yaml") is not None,
            "updated_at": project["updated_at"],
        }

    def list_map_projects(self) -> list[dict[str, Any]]:
        return [
            self._map_summary(project)
            for project in sorted(
                self._map_projects.values(), key=lambda value: value["map_name"]
            )
        ]

    def get_map_project(self, map_name: str) -> dict[str, Any] | None:
        project = self._map_projects.get(map_name)
        if project is None:
            return None
        return {**self._map_summary(project), **deepcopy(project)}

    def get_public_map_draft(self, map_name: str) -> dict[str, Any] | None:
        project = self.get_map_project(map_name)
        if project is None:
            return None
        return _public_draft_from_project(project)

    def save_public_map_draft(
        self,
        map_name: str,
        draft: dict[str, Any],
        expected_revision: int,
        staged_sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        existing = self._map_projects.get(map_name)
        current_revision = int(existing["draft_revision"]) if existing else 0
        if current_revision != expected_revision:
            raise MapDraftRevisionConflict
        project_snapshot = deepcopy(self._map_projects)
        source_snapshot = deepcopy(self._map_project_sources)
        try:
            payload = _normalize_map_payload(
                map_name,
                _public_draft_payload(map_name, draft),
                existing,
            )
            self._map_projects[map_name] = {
                "map_name": map_name,
                "format_version": int(draft["format_version"]),
                "payload": payload,
                "building_yaml": None,
                "building_yaml_name": None,
                "files": [],
                "fleet": None,
                "robots": [],
                "draft_revision": current_revision + 1,
                "updated_at": datetime.now(SEOUL),
            }
            project_sources = self._map_project_sources.setdefault(map_name, {})
            for source in staged_sources:
                stored = {
                    **_new_map_project_source(source),
                    "map_name": map_name,
                    "created_at": datetime.now(SEOUL),
                }
                if stored["source_uuid"] in project_sources:
                    raise MapProjectSourceValidationError(
                        "staged source UUID has already been promoted"
                    )
                project_sources[stored["source_uuid"]] = stored
            for source_type, source_uuid in draft.get("source_uuids", {}).items():
                stored = project_sources.get(source_uuid)
                if stored is None or stored["source_type"] != source_type:
                    raise MapProjectSourceValidationError(
                        "source UUID is absent, cross-project, or has the wrong type"
                    )
        except Exception:
            self._map_projects = project_snapshot
            self._map_project_sources = source_snapshot
            raise
        return self.get_public_map_draft(map_name)  # type: ignore[return-value]

    def delete_public_map_draft(self, map_name: str) -> None:
        project = self._map_projects.get(map_name)
        if project is None:
            raise MapProjectNotFound
        active = self._map_publications.get(map_name)
        if active is None:
            del self._map_projects[map_name]
            self._map_project_sources.pop(map_name, None)
            return
        snapshot = active.get("manifest", {}).get("draft_snapshot")
        if not isinstance(snapshot, dict):
            raise PublishedMapProjectDeleteConflict
        restored_payload = _normalize_map_payload(
            map_name, _public_draft_payload(map_name, snapshot), project
        )
        self._map_projects[map_name] = {
            "map_name": map_name,
            "format_version": int(snapshot["format_version"]),
            "payload": restored_payload,
            "building_yaml": None,
            "building_yaml_name": None,
            "files": [],
            "fleet": None,
            "robots": [],
            "draft_revision": int(active["draft_revision"]),
            "updated_at": datetime.now(SEOUL),
        }
        referenced = set(snapshot.get("source_uuids", {}).values())
        self._map_project_sources[map_name] = {
            source_uuid: source
            for source_uuid, source in self._map_project_sources.get(
                map_name, {}
            ).items()
            if source_uuid in referenced
        }

    def active_revision(self, map_name: str) -> str | None:
        publication = self._map_publications.get(map_name)
        return str(publication["map_revision"]) if publication else None

    def deployment_failure_events(self, map_name: str) -> list[dict[str, Any]]:
        return []

    def store_map_project_source(
        self, map_name: str, source: dict[str, Any]
    ) -> dict[str, Any]:
        if map_name not in self._map_projects:
            raise MapProjectNotFound
        stored = {
            **_new_map_project_source(source),
            "map_name": map_name,
            "created_at": datetime.now(SEOUL),
        }
        self._map_project_sources.setdefault(map_name, {})[stored["source_uuid"]] = stored
        return deepcopy(stored)

    def get_map_project_source(
        self, map_name: str, source_uuid: str
    ) -> dict[str, Any] | None:
        stored = self._map_project_sources.get(map_name, {}).get(source_uuid)
        return deepcopy(stored) if stored is not None else None

    def save_map_project(
        self, map_name: str, project: dict[str, Any], expected_revision: int | None
    ) -> dict[str, Any]:
        existing = self._map_projects.get(map_name)
        current_revision = existing["draft_revision"] if existing else None
        if expected_revision is not None and current_revision != expected_revision:
            raise MapDraftRevisionConflict
        normalized = _normalize_map_payload(map_name, project["payload"], existing)
        saved = {
            "map_name": map_name,
            **deepcopy(project),
            "payload": normalized,
            "files": [dict(value) for value in project.get("files", [])],
            "fleet": deepcopy(project.get("fleet")),
            "robots": [dict(value) for value in project.get("robots", [])],
            "draft_revision": (current_revision or 0) + 1,
            "updated_at": datetime.now(SEOUL),
        }
        self._map_projects[map_name] = saved
        return self.get_map_project(map_name)  # type: ignore[return-value]

    def delete_map_project(self, map_name: str) -> None:
        if map_name not in self._map_projects:
            raise MapProjectNotFound
        if map_name in self._map_publications:
            raise PublishedMapProjectDeleteConflict
        del self._map_projects[map_name]
        self._map_project_sources.pop(map_name, None)

    def validate_map_project(self, map_name: str) -> dict[str, Any]:
        project = self._map_projects.get(map_name)
        if project is None:
            raise MapProjectNotFound
        errors = _validate_map_draft(project)
        return {"valid": not errors, "errors": errors}

    def publish_map_project(
        self, map_name: str, publication: dict[str, Any]
    ) -> dict[str, Any]:
        project = self._map_projects.get(map_name)
        if project is None:
            raise MapProjectNotFound
        errors = _validate_map_draft(project)
        if errors:
            raise MapProjectValidationError(errors)
        if not publication["map_revision"].startswith(f"{map_name}:"):
            raise MapRevisionContentConflict
        existing_by_revision = self._map_publications_by_revision.get(
            publication["map_revision"]
        )
        identity = {
            **deepcopy(publication),
            "map_name": map_name,
            "draft_revision": project["draft_revision"],
        }
        if existing_by_revision:
            if any(existing_by_revision.get(key) != value for key, value in identity.items()):
                raise MapRevisionContentConflict
            return deepcopy(existing_by_revision)
        errors = _validate_publication_artifacts(project, publication)
        if errors:
            raise MapProjectValidationError(errors)
        self._map_features[publication["map_revision"]] = [
            _public_feature_projection(
                map_name, publication["map_revision"], feature
            )
            for feature in project["payload"].get("publicFeatures", [])
        ]
        result = {
            **deepcopy(publication),
            "map_name": map_name,
            "draft_revision": project["draft_revision"],
            "state": "published",
            "published_at": datetime.now(SEOUL),
        }
        previous = self._map_publications.get(map_name)
        if previous:
            previous["state"] = "retired"
        self._map_publications[map_name] = result
        self._map_publications_by_revision[publication["map_revision"]] = result
        return deepcopy(result)

    def get_published_map(self, map_name: str) -> dict[str, Any] | None:
        publication = self._map_publications.get(map_name)
        return deepcopy(publication) if publication else None

    def list_projected_map_features(
        self, map_revision: str
    ) -> list[dict[str, Any]]:
        return deepcopy(self._map_features.get(map_revision, []))

    def list_devices(self) -> list[dict[str, object]]:
        return []

    def list_registered_robot_ids(self) -> set[str]:
        return {"PK_01", "PK_02"}

    def ingest_robot_status(self, status: dict[str, Any]) -> None:
        existing = self._device_states.get(status["robot_id"])
        if existing and existing["details"]["session_id"] == status["session_id"] and existing["details"]["sequence"] >= status["sequence"]:
            raise RuntimeContextConflict
        state, health = MySqlFmsRepository._project_robot_state(status)
        self._device_states[status["robot_id"]] = {
            "device_id": status["robot_id"],
            "state": state,
            "health": health,
            "current_job_step_id": status["task_context"]["job_step_id"] if status["task_context"]["active"] else None,
            "details": {
                "session_id": status["session_id"],
                "sequence": status["sequence"],
                "map_revision": status["map_revision"],
                "twist": deepcopy(status["twist"]),
                "navigation_state": status["navigation_state"],
                "safety_state": status["safety_state"],
                "telemetry_valid": status["telemetry_valid"],
                "task_context": deepcopy(status["task_context"]),
                "received_at": datetime.now(SEOUL),
            },
        }

    def get_device_state(self, robot_id: str) -> dict[str, Any] | None:
        state = self._device_states.get(robot_id)
        return deepcopy(state) if state else None

    def ingest_task_event(self, event: dict[str, Any]) -> dict[str, Any]:
        existing = self._task_events.get(event["event_id"])
        if existing:
            identity, result = existing
            if identity != event:
                raise RuntimeContextConflict
            return deepcopy(result)
        context = event["task_context"]
        step = self._steps.get(context["job_step_id"])
        claim_contexts = (
            claimed[1]["task_context"] for claimed in self._claims.values()
        )
        exact_claim = any(claimed == context for claimed in claim_contexts)
        if step is None or step["job_id"] != context["job_id"] or step["assignment_revision"] != context["assignment_revision"] or step["assigned_device_id"] != event["robot_id"] or step["rmf_task_id"] != context["rmf_task_id"] or not exact_claim:
            raise RuntimeContextConflict
        if step["state"] in {"succeeded", "failed", "cancelled"}:
            raise RuntimeContextConflict
        if event["event_type"] == "arrived" and step["state"] != "running":
            raise RuntimeContextConflict
        if event["event_type"] in {"failed", "canceled"} and step["state"] not in {"pending", "running"}:
            raise RuntimeContextConflict
        if event["event_type"] != "started":
            status = self._device_states.get(event["robot_id"])
            details = status.get("details", {}) if status else {}
            received_at = details.get("received_at")
            if (
                details.get("session_id") != event.get("session_id")
                or details.get("map_revision") != context["map_revision"]
                or details.get("task_context") != context
                or not isinstance(received_at, datetime)
                or (datetime.now(SEOUL) - received_at).total_seconds() > 2.0
            ):
                raise RuntimeContextConflict
        state, event_type = {
            "started": ("running", "navigation.segment.started"),
            "arrived": ("succeeded", "navigation.waypoint.arrived"),
            "canceled": ("cancelled", "navigation.segment.cancelled"),
            "failed": ("failed", "navigation.segment.failed"),
        }[event["event_type"]]
        if event["event_type"] == "arrived":
            twist = details["twist"]
            if details["telemetry_valid"] is not True:
                state = "failed"
            elif details["safety_state"] != 0:
                state = "failed"
            elif details["navigation_state"] != 2:
                state = "failed"
            elif (
                abs(float(twist["linear_x_mps"])) > 0.02
                or abs(float(twist["angular_z_rps"])) > 0.05
            ):
                state = "failed"
        step["state"] = state
        self._append_event(step["job_id"], step["job_step_id"], event_type, {"primary_reason": event["reason_code"]})
        result = {"event_id": self._events[step["job_id"]][-1]["event_id"], "event_type": event_type}
        self._task_events[event["event_id"]] = (deepcopy(event), result)
        return deepcopy(result)

    def list_inventory(self) -> list[dict[str, object]]:
        return []

    def list_jobs(self) -> list[dict[str, object]]:
        return []

    def adjust_inventory(self, *args, **kwargs):
        raise InventoryLotNotFound

    def create_job(self, job: dict[str, Any]) -> dict[str, Any]:
        job_id = self._next_job_id
        self._next_job_id += 1
        created_at = datetime.now(SEOUL)
        steps = []
        for requested in job["steps"]:
            step_id = self._next_step_id
            self._next_step_id += 1
            step = {
                "job_step_id": step_id,
                "job_id": job_id,
                **deepcopy(requested),
                "state": "pending",
                "assigned_device_id": None,
                "assignment_revision": 0,
                "rmf_task_id": None,
                "result": None,
                "started_at": None,
                "completed_at": None,
            }
            self._steps[step_id] = step
            steps.append(step)
        self._jobs[job_id] = {
            "job_id": job_id,
            **deepcopy(job),
            "state": "queued",
            "created_at": created_at,
        }
        self._events[job_id] = []
        self._append_event(job_id, None, "job.created", {"job_code": job["job_code"], "step_count": len(steps)})
        return {
            "job_id": job_id,
            "job_code": job["job_code"],
            "state": "queued",
            "steps": [self._created_step(step) for step in steps],
        }

    @staticmethod
    def _created_step(step: dict[str, Any]) -> dict[str, Any]:
        return {key: step.get(key) for key in ("job_step_id", "step_no", "action_type", "executor_type", "target_location_id", "state")}

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        detail = {key: deepcopy(value) for key, value in job.items() if key != "steps"}
        detail["steps"] = [deepcopy(step) for step in sorted(self._steps.values(), key=lambda row: row["step_no"]) if step["job_id"] == job_id]
        return detail

    def get_job_timeline(self, job_id: int) -> list[dict[str, Any]] | None:
        if job_id not in self._jobs:
            return None
        return deepcopy(self._events[job_id])

    def _append_event(self, job_id: int, step_id: int | None, event_type: str, payload: dict[str, Any]) -> None:
        event_id = self._next_event_id
        self._next_event_id += 1
        self._events[job_id].append(
            {
                "event_id": event_id,
                "event_uuid": str(uuid.uuid4()),
                "occurred_at": datetime.now(SEOUL),
                "job_step_id": step_id,
                "severity": "info",
                "category": "operation" if event_type == "job.created" else "rmf",
                "event_type": event_type,
                "message": None,
                "payload": deepcopy(payload),
            }
        )

    def dispatch_step(self, job_step_id: int, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        step = self._steps.get(job_step_id)
        if step is None:
            raise JobStepNotFound
        fingerprint = {
            "job_step_id": job_step_id,
            "actor": request["actor"],
            "assigned_device_id": request.get("assigned_device_id"),
            "retry": request.get("retry", False),
        }
        existing = self._dispatches.get(idempotency_key)
        if existing:
            previous, response = existing
            if previous != fingerprint:
                raise IdempotencyConflict
            return deepcopy(response)
        retry = request.get("retry", False)
        invalid_state = (not retry and step["state"] != "pending") or (
            retry and step["state"] != "failed"
        )
        if invalid_state or any(
            candidate["job_id"] == step["job_id"]
            and candidate["step_no"] < step["step_no"]
            and candidate["state"] != "succeeded"
            for candidate in self._steps.values()
        ):
            raise JobStepNotDispatchable
        if any(
            response["job_step_id"] == job_step_id and response["state"] in {"pending", "sent"}
            for _, response in self._dispatches.values()
        ):
            raise JobStepNotDispatchable
        if retry:
            step["state"] = "pending"
            step["retry_count"] = step.get("retry_count", 0) + 1
        channel, message_type = MySqlFmsRepository._dispatch_kind(step["executor_type"])
        payload = {
            "request": fingerprint,
            "job_id": step["job_id"],
            "job_step_id": job_step_id,
            "step_no": step["step_no"],
            "action_type": step["action_type"],
            "target_location_id": step.get("target_location_id"),
            "input": deepcopy(step.get("input", {})),
        }
        response = {
            "message_id": str(uuid.uuid4()),
            "idempotency_key": idempotency_key,
            "job_id": step["job_id"],
            "job_step_id": job_step_id,
            "channel": channel,
            "message_type": message_type,
            "state": "pending",
            "payload": payload,
        }
        self._dispatches[idempotency_key] = (fingerprint, response)
        self._append_event(step["job_id"], job_step_id, "navigation.segment.dispatched", {"message_id": response["message_id"]})
        return deepcopy(response)

    def record_step_outcome(self, job_step_id: int, state: str) -> None:
        if state not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("state must be terminal")
        step = self._steps.get(job_step_id)
        if step is None:
            raise JobStepNotFound
        step["state"] = state
        for _, response in self._dispatches.values():
            if response["job_step_id"] == job_step_id and response["state"] == "pending":
                response["state"] = "completed"

    def record_rmf_acceptance(self, job_step_id: int, rmf_task_id: str, robot_id: str) -> None:
        step = self._steps.get(job_step_id)
        if step is None:
            raise JobStepNotFound
        step["rmf_task_id"] = rmf_task_id
        step["assigned_device_id"] = robot_id
        step["assignment_revision"] += 1

    def claim_rmf_dispatches(self, worker_id: str, limit: int) -> list[dict[str, Any]]:
        del worker_id
        claimed = []
        for _, response in self._dispatches.values():
            if len(claimed) >= limit:
                break
            if response["channel"] == "rmf" and response["state"] == "pending":
                response["state"] = "sent"
                response["payload"]["target_waypoint"] = response["payload"].get("input", {}).get("waypoint")
                response["payload"]["fleet_name"] = response["payload"].get("input", {}).get("fleet_name")
                response["payload"]["request_time_ms"] = int(datetime.now(SEOUL).timestamp() * 1000)
                claimed.append(deepcopy(response))
        return claimed

    def record_rmf_dispatch_acceptance(
        self, message_id: str, acceptance: dict[str, Any]
    ) -> dict[str, Any]:
        message = next(
            (response for _, response in self._dispatches.values() if response["message_id"] == message_id),
            None,
        )
        if message is None:
            raise DispatchMessageNotFound
        if message["state"] != "sent":
            if message["state"] != ("acknowledged" if acceptance["accepted"] else "failed"):
                raise JobStepNotDispatchable
            step = self._steps[message["job_step_id"]]
            if acceptance["accepted"] and (
                step["rmf_task_id"] != acceptance["rmf_task_id"]
                or step["assigned_device_id"] != acceptance["assigned_device_id"]
            ):
                raise IdempotencyConflict
            return {
                "message_id": message_id,
                "job_step_id": message["job_step_id"],
                "state": message["state"],
                "rmf_task_id": step["rmf_task_id"] if acceptance["accepted"] else None,
            }
        pending_assignment = bool(
            not acceptance["accepted"] and acceptance.get("rmf_task_id")
        )
        pending_rmf_task_id = message.get("pending_rmf_task_id")
        if (
            pending_rmf_task_id is not None
            and acceptance.get("rmf_task_id") != pending_rmf_task_id
        ):
            raise IdempotencyConflict
        if acceptance["accepted"]:
            self.record_rmf_acceptance(
                message["job_step_id"],
                acceptance["rmf_task_id"],
                acceptance["assigned_device_id"],
            )
            message["state"] = "acknowledged"
        elif not pending_assignment:
            message["state"] = "failed"
        else:
            message["pending_rmf_task_id"] = acceptance["rmf_task_id"]
        return {
            "message_id": message_id,
            "job_step_id": message["job_step_id"],
            "state": message["state"],
            "rmf_task_id": acceptance.get("rmf_task_id") if acceptance["accepted"] or pending_assignment else None,
        }

    def claim_command(self, rmf_task_id: str, request: dict[str, Any]) -> dict[str, Any]:
        step = next((row for row in self._steps.values() if row["rmf_task_id"] == rmf_task_id), None)
        if step is None:
            raise JobStepNotFound
        if step["state"] not in {"pending", "running"}:
            raise CommandClaimConflict
        claim_key = (rmf_task_id, request["execution_id"])
        existing = self._claims.get(claim_key)
        if existing:
            identity, response = existing
            if identity != request:
                raise CommandClaimConflict
            return deepcopy(response)
        if step["assigned_device_id"] != request["robot_id"]:
            raise CommandClaimConflict
        response = {
            "task_context": {
                "active": True,
                "job_id": step["job_id"],
                "job_step_id": step["job_step_id"],
                "assignment_revision": step["assignment_revision"],
                "rmf_task_id": rmf_task_id,
                "command_id": str(uuid.uuid4()),
                "map_revision": request["map_revision"],
                "command_source": "rmf",
            }
        }
        self._claims[claim_key] = (deepcopy(request), response)
        return deepcopy(response)
