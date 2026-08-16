"""FMS의 영속성, 트랜잭션, 상태 전이를 소유하는 Repository 계층.

운영 구현은 MySQL의 행 잠금과 commit으로 일관성을 보장하고, 메모리 구현은
같은 외부 계약과 상태 전이를 단위 테스트에서 결정적으로 재현한다.
"""


import base64
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import threading
from typing import Any, Protocol
import uuid
from zoneinfo import ZoneInfo

import yaml

from .database import Database
from control_tower.task_manager.outbound_planner import (
    InventoryLotSnapshot,
    OrderLine,
    OutboundOrder,
    OutboundPlanner,
    PlanningLocations,
)
from control_tower.task_manager.outbound_sequence import planned_outbound_steps


SEOUL = ZoneInfo("Asia/Seoul")


class FmsRepository(Protocol):
    """HTTP API와 TCP ingestion이 요구하는 저장소 유스케이스 계약."""
    def ping(self) -> bool: ...

    def list_devices(self) -> list[dict[str, object]]: ...

    def list_inventory(self) -> list[dict[str, object]]: ...

    def list_jobs(self) -> list[dict[str, object]]: ...

    def create_job(self, job: dict[str, Any]) -> dict[str, Any]: ...

    def create_outbound_order(
        self, request: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]: ...

    def get_job(self, job_id: int) -> dict[str, Any] | None: ...

    def get_job_timeline(self, job_id: int) -> list[dict[str, Any]] | None: ...

    def complete_worker_packing(
        self, job_id: int, request: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]: ...

    def assign_job_resources(
        self, job_id: int, assignment: dict[str, Any]
    ) -> dict[str, Any]: ...

    def record_load_attempt(
        self, job_step_id: int, request: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]: ...

    def record_pick_recovery(
        self, job_step_id: int, request: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]: ...

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

    def get_projected_location(self, location_code: str) -> dict[str, Any] | None: ...

    def list_projected_map_features(self, map_revision: str) -> list[dict[str, Any]]: ...

    def record_map_project_changes(
        self, map_name: str, changes: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...

    def list_operation_events(
        self,
        from_at: datetime | None,
        to_at: datetime | None,
        limit: int,
        before_at: datetime | None = None,
        before_event_id: int | None = None,
    ) -> list[dict[str, Any]]: ...


# 상위 경계가 안정적인 HTTP/프로토콜 오류로 변환하는 도메인 예외들이다.
class InventoryLotNotFound(Exception):
    pass


class InventoryQuantityConflict(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


class OutboundOrderInsufficientStock(Exception):
    def __init__(self, shortages: tuple[dict[str, Any], ...]):
        super().__init__("insufficient stock")
        self.shortages = shortages


class OutboundOrderProductNotFound(Exception):
    def __init__(self, product_reference: str, code: str = "PRODUCT_NOT_FOUND"):
        super().__init__(product_reference)
        self.product_reference = product_reference
        self.code = code


class OutboundOrderActiveMapUnavailable(Exception):
    pass


class JobNotFound(Exception):
    pass


class ManualAcknowledgementRequired(Exception):
    def __init__(self, item_ids: tuple[int, ...]):
        super().__init__("manual-required items must be acknowledged")
        self.item_ids = item_ids


class WorkerCompletionConflict(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class PickRecoveryConflict(Exception):
    pass


class ResourceAssignmentConflict(Exception):
    pass


class ResourceUnavailable(Exception):
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

LEGACY_WAYPOINT_CATEGORIES = {
    "대기": "holding",
    "주차": "parking",
    "홈": "home",
    "충전": "charger",
    "픽업": "pickup",
    "드랍오프": "dropoff",
    "설비": "equipment",
    "일반": "waypoint",
}

CANONICAL_WAYPOINT_CATEGORIES = frozenset(
    {
        "waypoint",
        "holding",
        "parking",
        "home",
        "charger",
        "pickup",
        "dropoff",
        "equipment",
    }
)

CATEGORY_LOCATION_TYPES = {
    "waypoint": "waypoint",
    "holding": "staging",
    "parking": "staging",
    "home": "staging",
    "charger": "charger",
    "pickup": "loading_dock",
    "dropoff": "loading_dock",
    "equipment": "workstation",
}

OPERATIONAL_ROLE_SPECS: dict[str, dict[str, Any]] = {
    "safety_zone": {
        "category": "holding",
        "location_type": "safe_node",
        "temperature_zone": None,
    },
    "charging_station": {
        "category": "charger",
        "location_type": "charger",
        "temperature_zone": None,
    },
    "loading_dock": {
        "category": "holding",
        "location_type": "loading_dock",
        "temperature_zone": "role-dependent",
        "parent_required": True,
    },
    "bottleneck_waiting_point": {
        "category": "holding",
        "location_type": "staging",
        "temperature_zone": "role-dependent",
        "parent_required": True,
    },
    "transit_waypoint": {
        "category": "waypoint",
        "location_type": "waypoint",
        "temperature_zone": None,
        "project_location": False,
    },
    "parking_spot": {
        "category": "parking",
        "location_type": "staging",
        "temperature_zone": None,
    },
    "inspection_point": {
        "category": "holding",
        "location_type": "staging",
        "temperature_zone": None,
    },
    "workcell_station": {
        "category": "equipment",
        "location_type": "workstation",
        "temperature_zone": None,
    },
}

LEGACY_OPERATIONAL_ROLES = {
    "ambient_storage_access": "loading_dock",
    "chilled_storage_access": "loading_dock",
    "frozen_storage_access": "loading_dock",
    "packing_handover": "loading_dock",
}

TEMPERATURE_ZONES = frozenset({"ambient", "chilled", "frozen"})


def _canonical_category(category: object) -> object:
    return LEGACY_WAYPOINT_CATEGORIES.get(category, category)


def _waypoint_projection(waypoint: dict[str, Any]) -> dict[str, Any]:
    """Return canonical operational fields shared by both repositories."""
    role = waypoint.get("operationalRole")
    category = _canonical_category(waypoint.get("category", "waypoint"))
    role_spec = OPERATIONAL_ROLE_SPECS.get(role)
    if role_spec:
        category = role_spec["category"]
        location_type = role_spec["location_type"]
    else:
        location_type = CATEGORY_LOCATION_TYPES.get(category, "waypoint")
    return {
        "operational_role": role,
        "category": category,
        "location_type": location_type,
        "temperature_zone": waypoint.get("temperatureZone"),
        "parent_location_code": waypoint.get("parentLocationCode"),
        "project_location": role_spec.get("project_location", True)
        if role_spec
        else True,
    }


def _bottleneck_projection(
    map_name: str, map_revision: str, zone: dict[str, Any]
) -> dict[str, Any]:
    return {
        "map_name": map_name,
        "map_revision": map_revision,
        "feature_code": zone["featureCode"],
        "feature_type": "bottleneck",
        "geometry": {
            "type": "Point",
            "coordinates": [float(zone["mapPose"][0]), float(zone["mapPose"][1])],
        },
        "properties": {
            "radius_m": float(zone["radiusM"]),
            "mutex_group": zone["mutexGroup"],
            **(
                {"entry_waiting_point": zone["entryWaitingPoint"]}
                if zone.get("entryWaitingPoint")
                else {}
            ),
            **(
                {"exit_waiting_point": zone["exitWaitingPoint"]}
                if zone.get("exitWaitingPoint")
                else {}
            ),
            **(
                {"aruco_marker_id": int(zone["arucoMarkerId"])}
                if zone.get("arucoMarkerId") is not None
                else {}
            ),
        },
        "active": True,
    }


def _fiducial_projection(
    map_name: str,
    map_revision: str,
    binding: dict[str, Any],
    location_id: int | None,
) -> dict[str, Any]:
    return {
        "map_name": map_name,
        "map_revision": map_revision,
        "feature_code": binding["featureCode"],
        "feature_type": "fiducial",
        "location_id": location_id,
        "marker_code": int(binding["markerId"]),
        "geometry": {
            "type": "Point",
            "coordinates": [
                float(binding["recognitionPose"][0]),
                float(binding["recognitionPose"][1]),
            ],
        },
        "properties": {
            "dictionary": binding["dictionary"],
            "target_location_code": binding["targetLocationCode"],
            "recognition_yaw": float(binding["recognitionPose"][2]),
            "pixel_size": float(binding["pixelSize"]),
        },
        "active": True,
    }


def _publication_identity(
    map_name: str, publication: dict[str, Any]
) -> dict[str, Any]:
    """Fields that make a published revision an immutable map artifact."""
    manifest = publication.get("manifest")
    revision_identity = (
        manifest.get("revision_identity") if isinstance(manifest, dict) else None
    )
    return {
        "map_name": map_name,
        "building_sha256": publication["building_sha256"],
        "nav_graph_sha256": publication["nav_graph_sha256"],
        "world_sha256": publication["world_sha256"],
        "revision_identity": (
            revision_identity if revision_identity is not None else manifest or {}
        ),
    }


def _canonical_public_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _assert_publication_expectations(
    current_draft: dict[str, Any],
    publication: dict[str, Any],
    source_lookup,
) -> None:
    expected = publication.get("expected_draft")
    if expected is None:
        return
    if not isinstance(expected, dict):
        raise MapDraftRevisionConflict
    snapshot = expected.get("draft_snapshot")
    source_manifest = expected.get("source_manifest")
    try:
        expected_hash = hashlib.sha256(_canonical_public_json(snapshot)).hexdigest()
        current_hash = hashlib.sha256(
            _canonical_public_json(current_draft)
        ).hexdigest()
    except (TypeError, ValueError):
        raise MapDraftRevisionConflict from None
    if (
        not isinstance(snapshot, dict)
        or not isinstance(source_manifest, list)
        or current_draft.get("draft_revision") != expected.get("draft_revision")
        or current_draft != snapshot
        or expected_hash != expected.get("snapshot_sha256")
        or current_hash != expected.get("snapshot_sha256")
        or current_draft.get("runtime_profile_hash")
        != expected.get("runtime_profile_hash")
    ):
        raise MapDraftRevisionConflict
    expected_source_uuids: dict[str, object] = {}
    for entry in source_manifest:
        if not isinstance(entry, dict) or not isinstance(entry.get("source_type"), str):
            raise MapDraftRevisionConflict
        source_type = entry["source_type"]
        if source_type in expected_source_uuids:
            raise MapDraftRevisionConflict
        expected_source_uuids[source_type] = entry.get("source_uuid")
        source = source_lookup(source_type, entry.get("source_uuid"))
        content = source.get("content_bytes") if isinstance(source, dict) else None
        if not isinstance(content, (bytes, bytearray)):
            raise MapDraftRevisionConflict
        raw = bytes(content)
        if (
            source.get("source_type") != source_type
            or source.get("source_uuid") != entry.get("source_uuid")
            or source.get("file_name") != entry.get("file_name")
            or source.get("mime_type") != entry.get("mime_type")
            or hashlib.sha256(raw).hexdigest() != entry.get("sha256")
            or len(raw) != entry.get("byte_size")
        ):
            raise MapDraftRevisionConflict
    if current_draft.get("source_uuids") != expected_source_uuids:
        raise MapDraftRevisionConflict


def _same_point(left: object, right: object) -> bool:
    """편집 전후의 2차원 좌표가 같아 identity를 보존할 수 있는지 판단한다."""
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
    """지도 초안에 안정적인 waypoint UUID와 operational identity를 보충한다.

    좌표가 유지된 기존 항목의 UUID, location code, map pose를 가능한 한
    재사용해 단순 재저장이 새로운 장소로 해석되지 않게 한다. P0에서
    user-authored lane은 계약이 아니므로 legacy laneDirections는 버린다.
    """
    normalized = deepcopy(payload)
    normalized["mapName"] = map_name
    normalized.pop("laneDirections", None)
    waypoints = normalized.setdefault("waypoints", [])
    previous_waypoints = (
        existing.get("payload", {}).get("waypoints", []) if existing else []
    )
    for index, waypoint in enumerate(waypoints):
        previous = previous_waypoints[index] if index < len(previous_waypoints) else {}
        waypoint["category"] = _canonical_category(
            waypoint.get("category", "waypoint")
        )
        role = waypoint.get("operationalRole")
        role = LEGACY_OPERATIONAL_ROLES.get(role, role)
        if role is None and waypoint["category"] in {"pickup", "dropoff"}:
            role = "loading_dock"
        if role is not None:
            waypoint["operationalRole"] = role
        role_spec = OPERATIONAL_ROLE_SPECS.get(role)
        if role_spec:
            waypoint["category"] = role_spec["category"]
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
        role_spec = OPERATIONAL_ROLE_SPECS.get(role)
        category = role_spec["category"] if role_spec else "waypoint"
        rmf_name = waypoint.get("rmf_waypoint_name") or waypoint["code"]
        waypoints.append(
            {
                "point": [x, y],
                "mapPose": [x, y, yaw],
                "yaw": yaw,
                "name": waypoint.get("display_name") or rmf_name,
                "rmfWaypointName": rmf_name,
                "category": category,
                "operationalRole": role or "transit_waypoint",
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


def _validate_map_draft(project: dict[str, Any]) -> list[str]:
    """식별자, 그래프, location, robot/fleet 관계의 모든 오류를 수집한다."""
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
        projection = _waypoint_projection(waypoint)
        category = projection["category"]
        role = projection["operational_role"]
        temperature_zone = projection["temperature_zone"]
        parent_location_code = projection["parent_location_code"]
        if category not in CANONICAL_WAYPOINT_CATEGORIES:
            errors.append(f"{name}: category가 canonical English 값이 아닙니다")
        if role is not None and role not in OPERATIONAL_ROLE_SPECS:
            errors.append(f"{name}: operationalRole이 지원되지 않습니다")
        if temperature_zone is not None and temperature_zone not in TEMPERATURE_ZONES:
            errors.append(f"{name}: temperatureZone이 지원되지 않습니다")
        role_spec = OPERATIONAL_ROLE_SPECS.get(role)
        if role_spec:
            expected_temperature = role_spec["temperature_zone"]
            if (
                expected_temperature != "role-dependent"
                and temperature_zone != expected_temperature
            ):
                errors.append(
                    f"{name}: temperatureZone이 operationalRole과 일치하지 않습니다"
                )
            expected_parent = role_spec.get("parent_location_code")
            if expected_parent and parent_location_code != expected_parent:
                errors.append(
                    f"{name}: parentLocationCode는 {expected_parent}이어야 합니다"
                )
            if role_spec.get("parent_required") and not parent_location_code:
                errors.append(f"{name}: parentLocationCode가 필요합니다")
            if not role_spec.get("project_location", True) and waypoint.get(
                "locationCode"
            ):
                errors.append(
                    f"{name}: Transit Waypoint에는 locationCode를 지정할 수 없습니다"
                )
        if parent_location_code is not None and (
            not isinstance(parent_location_code, str)
            or not parent_location_code.strip()
            or len(parent_location_code) > 96
        ):
            errors.append(f"{name}: parentLocationCode 형식이 잘못됐습니다")
        location_code = waypoint.get("locationCode")
        if category != "waypoint" and not location_code:
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
    feature_codes: set[str] = set()
    for index, zone in enumerate(project["payload"].get("bottleneckZones", []), start=1):
        label = zone.get("featureCode") or f"bottleneckZones[{index}]"
        feature_code = zone.get("featureCode")
        if (
            not isinstance(feature_code, str)
            or not feature_code.strip()
            or len(feature_code) > 128
        ):
            errors.append(f"{label}: featureCode 형식이 잘못됐습니다")
        elif feature_code in feature_codes:
            errors.append(f"{feature_code}: featureCode가 중복됩니다")
        else:
            feature_codes.add(feature_code)
        if zone.get("featureType") != "bottleneck":
            errors.append(f"{label}: featureType은 bottleneck이어야 합니다")
        map_pose = zone.get("mapPose")
        if (
            not isinstance(map_pose, list)
            or len(map_pose) != 2
            or not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                for value in map_pose
            )
        ):
            errors.append(f"{label}: mapPose는 유한한 [x, y]여야 합니다")
        radius = zone.get("radiusM")
        if (
            not isinstance(radius, (int, float))
            or isinstance(radius, bool)
            or not math.isfinite(float(radius))
            or float(radius) <= 0
        ):
            errors.append(f"{label}: radiusM은 0보다 큰 유한값이어야 합니다")
        mutex_group = zone.get("mutexGroup")
        if (
            not isinstance(mutex_group, str)
            or not mutex_group.strip()
            or len(mutex_group) > 64
        ):
            errors.append(f"{label}: mutexGroup이 필요합니다")
        for key in ("entryWaitingPoint", "exitWaitingPoint"):
            waiting_code = zone.get(key)
            if waiting_code is None:
                continue
            waiting = next(
                (
                    waypoint
                    for waypoint in waypoints
                    if waypoint.get("locationCode") == waiting_code
                ),
                None,
            )
            if waiting is None or waiting.get("operationalRole") != "bottleneck_waiting_point":
                errors.append(f"{label}: {key}는 Bottleneck Waiting Point여야 합니다")
        marker_id = zone.get("arucoMarkerId")
        if marker_id is not None and (
            not isinstance(marker_id, int)
            or isinstance(marker_id, bool)
            or marker_id < 0
        ):
            errors.append(f"{label}: arucoMarkerId는 0 이상의 정수여야 합니다")
    waypoint_categories = {
        (waypoint.get("rmfWaypointName") or waypoint.get("name")): waypoint.get("category")
        for waypoint in waypoints
    }
    robot_ids: set[str] = set()
    gazebo_names: set[str] = set()
    for robot in project.get("robots", []):
        robot_id = robot.get("robot_id", "")
        if not robot_id or robot_id in robot_ids:
            errors.append(f"{robot_id or '<ID 없음>'}: 로봇 ID가 중복되거나 비었습니다")
        robot_ids.add(robot_id)
        gz_name = robot.get("gz_name", "")
        normalized_gz_name = gz_name.casefold() if isinstance(gz_name, str) else ""
        if not normalized_gz_name or normalized_gz_name in gazebo_names:
            errors.append(
                f"{gz_name or '<gz_name 없음>'}: gz_name이 중복되거나 비었습니다"
            )
        gazebo_names.add(normalized_gz_name)
        station = robot.get("charger_waypoint_name")
        required_category = "charger" if robot.get("kind") == "mobile" else "equipment"
        if not station or waypoint_categories.get(station) != required_category:
            errors.append(
                f"{robot_id}: {'충전' if required_category == 'charger' else '설비'} Waypoint 연결이 필요합니다"
            )
        if robot.get("kind") == "mobile" and project.get("fleet") is None:
            errors.append(f"{robot_id}: mobile robot에는 fleet 설정이 필요합니다")
    return errors


def _validate_publication_artifacts(
    project: dict[str, Any], publication: dict[str, Any]
) -> list[str]:
    """artifact 내용 해시와 현재 초안/nav graph의 일치를 검증한다."""
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
    manifest = publication.get("manifest")
    revision_identity = (
        manifest.get("revision_identity") if isinstance(manifest, dict) else None
    )
    hash_identity = revision_identity or {
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
        if _canonical_category(waypoint.get("category")) == "equipment":
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
    """문자열 또는 객체로 반환될 수 있는 MySQL JSON을 객체로 통일한다."""
    return json.loads(value) if isinstance(value, str) else value


def _mysql_datetime(value: datetime | None) -> datetime | None:
    """aware 값을 MySQL +09:00 세션에 기록할 naive 서울 시각으로 바꾼다."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(SEOUL).replace(tzinfo=None)


def _seoul_datetimes(row: dict[str, object]) -> dict[str, object]:
    """MySQL에서 읽은 naive datetime을 Asia/Seoul aware 값으로 복원한다."""
    for key, value in row.items():
        if isinstance(value, datetime) and value.tzinfo is None:
            row[key] = value.replace(tzinfo=SEOUL)
    return row


def _json_safe(value: object) -> object:
    """Detach repository responses into JSON-compatible idempotency payloads."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(nested) for nested in value]
    return value


class MySqlFmsRepository:
    """행 잠금과 명시적 commit으로 FMS 상태를 원자적으로 갱신하는 운영 구현."""
    def __init__(self, database: Database):
        self.database = database

    def _all(
        self, sql: str, params: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        """읽기 쿼리 결과를 dict와 서울 시간대 값으로 정규화한다."""
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
                       rmf_waypoint_name, category, operational_role,
                       temperature_zone, parent_location_code, x, y, yaw,
                       map_x, map_y, map_yaw, active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, 1)
                    """,
                    (
                        waypoint["waypointUuid"],
                        project_id,
                        seq,
                        waypoint.get("locationCode"),
                        waypoint["rmfWaypointName"],
                        waypoint.get("category", "waypoint"),
                        waypoint.get("operationalRole", "transit_waypoint"),
                        waypoint.get("temperatureZone"),
                        waypoint.get("parentLocationCode"),
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
        """지도 초안과 모든 하위 항목을 한 트랜잭션에서 저장한다.

        행 잠금과 expected revision으로 동시 편집 충돌을 감지하며, JSON 원본과
        검색/조인용 정규화 테이블이 서로 다른 버전으로 남지 않게 함께 commit한다.
        """
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
                           rmf_waypoint_name, category, operational_role,
                           temperature_zone, parent_location_code, x, y, yaw,
                           map_x, map_y, map_yaw, active)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s, %s, 1)
                        """,
                        (
                            waypoint["waypointUuid"], project_id, seq,
                            waypoint.get("locationCode"), name,
                            waypoint.get("category", "waypoint"),
                            waypoint.get("operationalRole", "transit_waypoint"),
                            waypoint.get("temperatureZone"),
                            waypoint.get("parentLocationCode"),
                            point[0], point[1], waypoint.get("yaw"),
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
        """실행 재현성을 위해 발행 이력이 없는 지도 초안만 삭제한다."""
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
        """현재 초안을 읽어 검증 오류를 fail-fast하지 않고 한 번에 반환한다."""
        project = self.get_map_project(map_name)
        if project is None:
            raise MapProjectNotFound
        errors = _validate_map_draft(project)
        return {"valid": not errors, "errors": errors}

    @staticmethod
    def _location_type(category: str, operational_role: str | None = None) -> str:
        role_spec = OPERATIONAL_ROLE_SPECS.get(operational_role)
        if role_spec:
            return str(role_spec["location_type"])
        canonical = _canonical_category(category)
        return CATEGORY_LOCATION_TYPES[str(canonical)]

    def publish_map_project(
        self, map_name: str, publication: dict[str, Any]
    ) -> dict[str, Any]:
        """검증된 초안과 세 artifact를 불변 map revision으로 발행한다.

        같은 revision 재요청은 콘텐츠가 같을 때만 멱등 성공하며, 다른 콘텐츠는
        충돌시켜 revision 이름이 언제나 같은 실행 산출물을 가리키게 한다.
        """
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

                def locked_source(source_type: str, source_uuid: object):
                    cursor.execute(
                        """
                        SELECT source_uuid, source_type, file_name, mime_type,
                               content_bytes
                        FROM map_project_sources
                        WHERE project_id = %s AND source_uuid = %s
                        FOR UPDATE
                        """,
                        (project_id, source_uuid),
                    )
                    source = cursor.fetchone()
                    return dict(source) if source is not None else None

                _assert_publication_expectations(
                    _public_draft_from_project(project), publication, locked_source
                )
                cursor.execute(
                    "SELECT * FROM map_revisions WHERE map_revision = %s",
                    (publication["map_revision"],),
                )
                existing = cursor.fetchone()
                if existing:
                    existing_publication = {
                        **dict(existing),
                        "manifest": _json(existing["manifest"]),
                    }
                    if (
                        int(existing["source_project_id"]) != project_id
                        or _publication_identity(map_name, existing_publication)
                        != _publication_identity(map_name, publication)
                    ):
                        raise MapRevisionContentConflict
                    connection.rollback()
                    result = dict(existing)
                    result.pop("source_project_id", None)
                    result["manifest"] = _json(result["manifest"])
                    return _seoul_datetimes(result)
                errors = _validate_map_draft(project)
                if errors:
                    raise MapProjectValidationError(errors)
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
                    projection = _waypoint_projection(waypoint)
                    if not projection["project_location"]:
                        continue
                    active_codes.append(location_code)
                    map_pose = waypoint["mapPose"]
                    parent_location_id = None
                    parent_location_code = projection["parent_location_code"]
                    if parent_location_code:
                        cursor.execute(
                            "SELECT location_id FROM locations WHERE location_code = %s",
                            (parent_location_code,),
                        )
                        parent = cursor.fetchone()
                        if parent is None:
                            raise MapProjectValidationError(
                                [f"{location_code}: parentLocationCode가 존재하지 않습니다"]
                            )
                        parent_location_id = parent["location_id"]
                    metadata = json.dumps(
                        {
                            "authoring_managed": True,
                            "active": True,
                            "waypoint_uuid": waypoint["waypointUuid"],
                            "map_revision": publication["map_revision"],
                            "operational_role": projection["operational_role"],
                            "rmf_category": projection["category"],
                            "parent_location_code": parent_location_code,
                        },
                        ensure_ascii=False,
                    )
                    location_type = projection["location_type"]
                    name = waypoint.get("name") or waypoint["rmfWaypointName"]
                    cursor.execute(
                        "SELECT location_type, map_name, metadata FROM locations WHERE location_code = %s",
                        (location_code,),
                    )
                    existing_location = cursor.fetchone()
                    if (
                        existing_location
                        and existing_location["map_name"] is not None
                        and existing_location["map_name"] != map_name
                    ):
                        raise MapProjectValidationError(
                            [f"{location_code}: 다른 published map이 소유합니다"]
                        )
                    if (
                        projection["operational_role"] is None
                        and projection["category"] == "pickup"
                        and existing_location
                    ):
                        location_type = existing_location["location_type"]
                    cursor.execute(
                        """
                        INSERT INTO locations
                          (parent_location_id, location_code, name, location_type,
                           temperature_zone, map_name,
                           rmf_waypoint_name, pose_x, pose_y, pose_yaw, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                          parent_location_id = %s, name = %s, location_type = %s,
                          temperature_zone = %s, map_name = %s,
                          rmf_waypoint_name = %s, pose_x = %s, pose_y = %s,
                          pose_yaw = %s, metadata = %s
                        """,
                        (
                            parent_location_id, location_code, name, location_type,
                            projection["temperature_zone"], map_name,
                            waypoint["rmfWaypointName"], map_pose[0], map_pose[1],
                            map_pose[2] if len(map_pose) >= 3 else None, metadata,
                            parent_location_id, name, location_type,
                            projection["temperature_zone"], map_name,
                            waypoint["rmfWaypointName"],
                            map_pose[0], map_pose[1],
                            map_pose[2] if len(map_pose) >= 3 else None, metadata,
                        ),
                    )
                for zone in project["payload"].get("bottleneckZones", []):
                    feature = _bottleneck_projection(
                        map_name, publication["map_revision"], zone
                    )
                    cursor.execute(
                        """
                        INSERT INTO map_features
                          (map_name, map_revision, feature_code, feature_type,
                           geometry, properties, active)
                        VALUES (%s, %s, %s, 'bottleneck', %s, %s, 1)
                        """,
                        (
                            feature["map_name"],
                            feature["map_revision"],
                            feature["feature_code"],
                            json.dumps(feature["geometry"], ensure_ascii=False),
                            json.dumps(feature["properties"], ensure_ascii=False),
                        ),
                    )
                for binding in project["payload"].get("fiducialBindings", []):
                    cursor.execute(
                        "SELECT location_id FROM locations WHERE location_code = %s",
                        (binding["targetLocationCode"],),
                    )
                    target = cursor.fetchone()
                    feature = _fiducial_projection(
                        map_name,
                        publication["map_revision"],
                        binding,
                        int(target["location_id"]) if target else None,
                    )
                    cursor.execute(
                        """
                        INSERT INTO map_features
                          (map_name, map_revision, feature_code, feature_type,
                           location_id, marker_code, geometry, properties, active)
                        VALUES (%s, %s, %s, 'fiducial', %s, %s, %s, %s, 1)
                        """,
                        (
                            feature["map_name"],
                            feature["map_revision"],
                            feature["feature_code"],
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
        """해당 지도에서 가장 최근에 발행된 실행 revision을 반환한다."""
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

    def get_projected_location(self, location_code: str) -> dict[str, Any] | None:
        rows = self._all(
            """
            SELECT location_id, parent_location_id, location_code, name,
                   location_type, temperature_zone, map_name,
                   rmf_waypoint_name, pose_x, pose_y, pose_yaw, metadata
            FROM locations WHERE location_code = %s
            """,
            (location_code,),
        )
        if not rows:
            return None
        rows[0]["metadata"] = _json(rows[0]["metadata"])
        return rows[0]

    def list_projected_map_features(self, map_revision: str) -> list[dict[str, Any]]:
        rows = self._all(
            """
            SELECT map_name, map_revision, feature_code, feature_type,
                   geometry, properties, active
            FROM map_features WHERE map_revision = %s
            ORDER BY feature_code
            """,
            (map_revision,),
        )
        for row in rows:
            row["geometry"] = _json(row["geometry"])
            row["properties"] = _json(row["properties"])
            row["active"] = bool(row["active"])
        return rows

    def record_map_project_changes(
        self, map_name: str, changes: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT 1 FROM map_projects WHERE map_name = %s",
                    (map_name,),
                )
                if cursor.fetchone() is None:
                    raise MapProjectNotFound
                events: list[dict[str, Any]] = []
                for change in changes:
                    event_uuid = str(uuid.uuid4())
                    occurred_at = datetime.now(SEOUL)
                    payload = {"map_name": map_name, "change": deepcopy(change)}
                    cursor.execute(
                        """
                        INSERT INTO operation_events
                          (event_uuid, occurred_at, severity, category,
                           event_type, message, payload)
                        VALUES (%s, %s, 'info', 'system',
                                'MAP_PROJECT_CHANGED', %s, %s)
                        """,
                        (
                            event_uuid,
                            _mysql_datetime(occurred_at),
                            change["summary"],
                            json.dumps(payload, ensure_ascii=False),
                        ),
                    )
                    events.append(
                        {
                            "event_id": int(cursor.lastrowid),
                            "event_uuid": event_uuid,
                            "occurred_at": occurred_at,
                            "actor_worker_id": None,
                            "device_id": None,
                            "job_id": None,
                            "job_step_id": None,
                            "incident_id": None,
                            "severity": "info",
                            "category": "system",
                            "event_type": "MAP_PROJECT_CHANGED",
                            "message": change["summary"],
                            "payload": payload,
                        }
                    )
                connection.commit()
                return events
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def list_operation_events(
        self,
        from_at: datetime | None,
        to_at: datetime | None,
        limit: int,
        before_at: datetime | None = None,
        before_event_id: int | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[object] = []
        if from_at is not None:
            conditions.append("occurred_at >= %s")
            params.append(_mysql_datetime(from_at))
        if to_at is not None:
            conditions.append("occurred_at < %s")
            params.append(_mysql_datetime(to_at))
        if before_at is not None and before_event_id is not None:
            cursor_at = _mysql_datetime(before_at)
            conditions.append(
                "(occurred_at < %s OR (occurred_at = %s AND event_id < %s))"
            )
            params.extend((cursor_at, cursor_at, before_event_id))
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        rows = self._all(
            """
            SELECT event_id, event_uuid, occurred_at, actor_worker_id,
                   device_id, job_id, job_step_id, incident_id, severity,
                   category, event_type, message, payload
            FROM operation_events
            """
            + where
            + " ORDER BY occurred_at DESC, event_id DESC LIMIT %s",
            tuple([*params, limit]),
        )
        for row in rows:
            row["payload"] = _json(row["payload"])
        return rows

    @staticmethod
    def _project_robot_state(status: dict[str, Any]) -> tuple[str, str]:
        """원시 telemetry 신호를 운영 화면용 state와 health로 축약한다."""
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
        """검증된 로봇 상태를 장치의 최신 projection으로 upsert한다."""
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
        """실행 문맥과 최신 telemetry를 확인해 Job Step을 전이한다.

        event UUID는 멱등 identity다. 특히 `arrived`는 같은 session/map/context의
        최근 상태와 실제 정지·안전·navigation 조건도 만족해야 성공한다.
        """
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
        """lot 행을 잠근 뒤 수량, 감사 이벤트, 멱등 응답을 함께 저장한다."""
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

    @staticmethod
    def _outbound_waypoint_value(waypoint: dict[str, Any], *names: str) -> Any:
        for name in names:
            if name in waypoint:
                return waypoint[name]
        return None

    def _outbound_planning_locations(
        self,
        cursor,
        required_zone_parents: dict[str, set[str]],
    ) -> PlanningLocations:
        """Resolve docks and chargers from a published manifest and location IDs."""
        cursor.execute(
            """
            SELECT map_name, manifest
            FROM map_revisions
            WHERE map_name = %s AND state = 'published'
            ORDER BY published_at DESC, map_revision DESC
            LIMIT 1
            FOR UPDATE
            """,
            ("trihouse_test_01",),
        )
        publications = cursor.fetchall()
        for publication in publications:
            manifest = _json(publication["manifest"]) or {}
            snapshot = manifest.get("draft_snapshot") or {}
            waypoints = snapshot.get("waypoints") or []
            if not isinstance(waypoints, list):
                continue
            loading: list[tuple[str, str | None, str | None]] = []
            charger_codes: list[str] = []
            for waypoint in waypoints:
                if not isinstance(waypoint, dict):
                    continue
                code = self._outbound_waypoint_value(
                    waypoint, "location_code", "locationCode", "code"
                )
                role = self._outbound_waypoint_value(
                    waypoint, "operational_role", "operationalRole"
                )
                if not isinstance(code, str) or not code:
                    continue
                if role == "loading_dock":
                    loading.append(
                        (
                            code,
                            self._outbound_waypoint_value(
                                waypoint,
                                "parent_location_code",
                                "parentLocationCode",
                            ),
                            self._outbound_waypoint_value(
                                waypoint, "temperature_zone", "temperatureZone"
                            ),
                        )
                    )
                elif role == "charging_station":
                    charger_codes.append(code)
            candidate_codes = sorted({code for code, _, _ in loading} | set(charger_codes))
            if not candidate_codes:
                continue
            placeholders = ",".join(["%s"] * len(candidate_codes))
            cursor.execute(
                f"""
                SELECT location_id, location_code, parent_location_id, map_name, metadata
                FROM locations
                WHERE location_code IN ({placeholders}) AND map_name = %s
                """,
                (*candidate_codes, publication["map_name"]),
            )
            location_rows: dict[str, dict[str, Any]] = {}
            for row in cursor.fetchall():
                metadata = _json(row.get("metadata")) or {}
                if metadata.get("active") is False:
                    continue
                location_rows[str(row["location_code"])] = dict(row)

            parent_codes = sorted(
                {parent for _, parent, _ in loading if isinstance(parent, str)}
            )
            parent_rows: dict[str, dict[str, Any]] = {}
            if parent_codes:
                parent_placeholders = ",".join(["%s"] * len(parent_codes))
                cursor.execute(
                    f"""
                    SELECT location_id, location_code, location_type, zone_code,
                           temperature_zone
                    FROM locations WHERE location_code IN ({parent_placeholders})
                    """,
                    tuple(parent_codes),
                )
                parent_rows = {
                    str(row["location_code"]): dict(row) for row in cursor.fetchall()
                }

            zone_docks: dict[str, int] = {}
            for zone, required_parents in required_zone_parents.items():
                choices = sorted(
                    (
                        code,
                        int(location_rows[code]["location_id"]),
                    )
                    for code, parent, waypoint_zone in loading
                    if code in location_rows
                    and parent in required_parents
                    and waypoint_zone == zone
                )
                if not choices:
                    break
                zone_docks[zone] = choices[0][1]
            if set(zone_docks) != set(required_zone_parents):
                continue

            packing_docks = sorted(
                int(location_rows[code]["location_id"])
                for code, parent, _ in loading
                if code in location_rows
                and isinstance(parent, str)
                and parent in parent_rows
                and (
                    parent_rows[parent].get("zone_code") == "packing"
                    or parent_rows[parent].get("location_type") == "workstation"
                )
            )
            chargers = sorted(
                int(location_rows[code]["location_id"])
                for code in charger_codes
                if code in location_rows
            )
            if packing_docks and chargers:
                return PlanningLocations(
                    zone_docks=zone_docks,
                    packing_docks=tuple(packing_docks),
                    charger_location_ids=tuple(chargers),
                )
        raise OutboundOrderActiveMapUnavailable(
            "published map does not contain the required zone docks, packing docks, and chargers"
        )

    def create_outbound_order(
        self, request: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        """Lock FEFO lots and persist the entire accepted order in one transaction."""
        fingerprint = json.loads(
            json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        event_uuid = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"trihouse:outbound-order:{idempotency_key}")
        )
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    INSERT IGNORE INTO operation_events
                      (event_uuid, occurred_at, severity, category,
                       event_type, message, payload)
                    VALUES (%s, NOW(6), 'info', 'operation',
                            'order.created', 'outbound product order created', %s)
                    """,
                    (
                        event_uuid,
                        json.dumps(
                            {
                                "idempotency_key": idempotency_key,
                                "request": fingerprint,
                                "response": None,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
                owns_idempotency_key = cursor.rowcount == 1
                if not owns_idempotency_key:
                    cursor.execute(
                        "SELECT payload FROM operation_events WHERE event_uuid = %s",
                        (event_uuid,),
                    )
                    existing = cursor.fetchone()
                    if existing is None:
                        raise RuntimeError("idempotency event was not readable")
                    payload = _json(existing["payload"]) or {}
                    if payload.get("request") != fingerprint:
                        raise IdempotencyConflict
                    if payload.get("response") is None:
                        raise RuntimeError("idempotency event has no committed response")
                    return deepcopy(payload["response"])

                external_reference = request.get("external_reference")
                if external_reference:
                    cursor.execute(
                        "SELECT job_id FROM jobs WHERE external_reference = %s",
                        (external_reference,),
                    )
                    if cursor.fetchone() is not None:
                        raise IdempotencyConflict

                resolved_lines: list[OrderLine] = []
                canonical_products: set[str] = set()
                for line_no, line in enumerate(request["items"], start=1):
                    product_reference = str(line["product_code"]).strip()
                    cursor.execute(
                        "SELECT DISTINCT product_code FROM inventory_lots WHERE product_code = %s",
                        (product_reference,),
                    )
                    exact = [str(row["product_code"]) for row in cursor.fetchall()]
                    if exact:
                        matches = exact
                    else:
                        cursor.execute(
                            """
                            SELECT DISTINCT product_code FROM inventory_lots
                            WHERE LOWER(item_name) = LOWER(%s)
                            ORDER BY product_code
                            """,
                            (product_reference,),
                        )
                        matches = [str(row["product_code"]) for row in cursor.fetchall()]
                    if not matches:
                        raise OutboundOrderProductNotFound(product_reference)
                    if len(matches) != 1:
                        raise OutboundOrderProductNotFound(
                            product_reference, "AMBIGUOUS_PRODUCT"
                        )
                    product_code = matches[0]
                    if product_code in canonical_products:
                        raise OutboundOrderProductNotFound(
                            product_reference, "DUPLICATE_PRODUCT"
                        )
                    canonical_products.add(product_code)
                    resolved_lines.append(
                        OrderLine(line_no, product_code, int(line["quantity"]))
                    )

                product_codes = sorted(canonical_products)
                placeholders = ",".join(["%s"] * len(product_codes))
                cursor.execute(
                    f"""
                    SELECT lot_id
                    FROM inventory_lots
                    WHERE product_code IN ({placeholders}) AND state = 'stored'
                    ORDER BY lot_id
                    """,
                    tuple(product_codes),
                )
                candidate_lot_ids = [
                    int(row["lot_id"]) for row in cursor.fetchall()
                ]
                lot_rows: list[dict[str, Any]] = []
                for lot_id in candidate_lot_ids:
                    cursor.execute(
                        """
                    SELECT lot.lot_id, lot.lot_code, lot.product_code, lot.item_name,
                           lot.temperature_zone, lot.location_id,
                           lot.available_qty, lot.reserved_qty, lot.expiry_date,
                           lot.received_at, parent.location_code AS parent_location_code,
                           parent.temperature_zone AS parent_temperature_zone
                    FROM inventory_lots lot
                    JOIN locations slot ON slot.location_id = lot.location_id
                    JOIN locations parent ON parent.location_id = slot.parent_location_id
                    WHERE lot.lot_id = %s AND lot.state = 'stored'
                    FOR UPDATE
                        """,
                        (lot_id,),
                    )
                    row = cursor.fetchone()
                    if row is not None:
                        lot_rows.append(dict(row))
                for row in lot_rows:
                    if row["temperature_zone"] != row["parent_temperature_zone"]:
                        raise OutboundOrderActiveMapUnavailable(
                            f"lot {row['lot_code']} temperature zone disagrees "
                            "with its parent warehouse"
                        )
                inventory = tuple(
                    InventoryLotSnapshot(
                        lot_id=int(row["lot_id"]),
                        lot_code=str(row["lot_code"]),
                        product_code=str(row["product_code"]),
                        item_name=row.get("item_name"),
                        temperature_zone=str(row["temperature_zone"]),
                        slot_location_id=int(row["location_id"]),
                        available_qty=int(row["available_qty"]),
                        reserved_qty=int(row["reserved_qty"]),
                        expiry_date=row.get("expiry_date"),
                        received_at=row.get("received_at"),
                    )
                    for row in lot_rows
                )
                required_zone_parents: dict[str, set[str]] = {}
                for row in lot_rows:
                    if int(row["available_qty"]) - int(row["reserved_qty"]) <= 0:
                        continue
                    required_zone_parents.setdefault(
                        str(row["temperature_zone"]), set()
                    ).add(str(row["parent_location_code"]))
                planning_locations = self._outbound_planning_locations(
                    cursor, required_zone_parents
                )
                job_identity = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"trihouse:outbound-job:{external_reference or idempotency_key}",
                ).hex[:24]
                outbound_order = OutboundOrder(
                    order_identity=job_identity,
                    external_reference=external_reference,
                    requested_by=str(request["requested_by"]),
                    priority=str(request["priority"]),
                    allow_partial_fulfillment=bool(
                        request["allow_partial_fulfillment"]
                    ),
                    items=tuple(resolved_lines),
                )
                plan = OutboundPlanner().plan(
                    outbound_order, inventory, planning_locations
                )
                if not plan.accepted:
                    available_by_product = {
                        code: sum(
                            candidate.reservable_qty
                            for candidate in inventory
                            if candidate.product_code == code
                        )
                        for code in product_codes
                    }
                    shortages = tuple(
                        {
                            "line_no": line.line_no,
                            "product_code": line.product_code,
                            "outstanding_quantity": max(
                                0,
                                line.quantity
                                - available_by_product.get(line.product_code, 0),
                            ),
                        }
                        for line in resolved_lines
                        if available_by_product.get(line.product_code, 0) < line.quantity
                    )
                    raise OutboundOrderInsufficientStock(shortages)

                job_code = f"OUT-{job_identity}"
                context = {
                    "source": "public_product_order",
                    "allow_partial_fulfillment": outbound_order.allow_partial_fulfillment,
                    "zone_order": [bundle.temperature_zone for bundle in plan.bundles],
                    "requested_quantity": plan.requested_quantity,
                    "fulfillable_quantity": plan.fulfillable_quantity,
                    "outstanding_quantity": plan.outstanding_quantity,
                }
                cursor.execute(
                    """
                    INSERT INTO jobs
                      (job_code, operation_type, priority, requested_by,
                       external_reference, destination_location_id, context)
                    VALUES (%s, 'outbound', %s, %s, %s, %s, %s)
                    """,
                    (
                        job_code,
                        outbound_order.priority,
                        outbound_order.requested_by,
                        external_reference,
                        plan.packing_dock_location_id,
                        json.dumps(context, ensure_ascii=False),
                    ),
                )
                job_id = int(cursor.lastrowid)

                for line in plan.lines:
                    if not line.allocations:
                        item_rows = [(None, line.requested_qty, 0, line.outstanding_qty)]
                    else:
                        item_rows = [
                            (
                                allocation.lot_id,
                                allocation.reserved_qty
                                + (
                                    line.outstanding_qty
                                    if index == len(line.allocations) - 1
                                    else 0
                                ),
                                allocation.reserved_qty,
                                line.outstanding_qty
                                if index == len(line.allocations) - 1
                                else 0,
                            )
                            for index, allocation in enumerate(line.allocations)
                        ]
                    for lot_id, requested_qty, reserved_qty, outstanding_qty in item_rows:
                        metadata = {
                            "line_no": line.line_no,
                            "reserved_quantity": reserved_qty,
                            "outstanding_quantity": outstanding_qty,
                        }
                        cursor.execute(
                            """
                            INSERT INTO job_items
                              (job_id, product_code, requested_qty, lot_id, metadata)
                            VALUES (%s, %s, %s, %s, %s)
                            """,
                            (
                                job_id,
                                line.product_code,
                                requested_qty,
                                lot_id,
                                json.dumps(metadata, ensure_ascii=False),
                            ),
                        )

                for step in planned_outbound_steps(plan):
                    cursor.execute(
                        """
                        INSERT INTO job_steps
                          (job_id, step_no, executor_type, action_type,
                           target_location_id, input)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            job_id,
                            step.step_no,
                            step.executor_type,
                            step.action_type,
                            step.target_location_id,
                            json.dumps(step.input, ensure_ascii=False),
                        ),
                    )

                row_by_lot_id = {int(row["lot_id"]): row for row in lot_rows}
                for line in plan.lines:
                    for allocation in line.allocations:
                        lot_row = row_by_lot_id[allocation.lot_id]
                        reserved_after = int(lot_row["reserved_qty"]) + allocation.reserved_qty
                        cursor.execute(
                            """
                            UPDATE inventory_lots SET reserved_qty = %s
                            WHERE lot_id = %s AND reserved_qty = %s
                              AND available_qty >= %s
                            """,
                            (
                                reserved_after,
                                allocation.lot_id,
                                lot_row["reserved_qty"],
                                reserved_after,
                            ),
                        )
                        if cursor.rowcount != 1:
                            raise InventoryQuantityConflict
                        lot_row["reserved_qty"] = reserved_after
                        cursor.execute(
                            """
                            INSERT INTO inventory_moves
                              (lot_id, job_id, move_type, quantity_delta,
                               quantity_after, reserved_delta, reserved_after,
                               recorded_by, note)
                            VALUES (%s, %s, 'reservation', 0, %s, %s, %s, %s, %s)
                            """,
                            (
                                allocation.lot_id,
                                job_id,
                                lot_row["available_qty"],
                                allocation.reserved_qty,
                                reserved_after,
                                outbound_order.requested_by,
                                f"outbound order line {line.line_no}",
                            ),
                        )

                response_items = [
                    {
                        "line_no": line.line_no,
                        "product_code": line.product_code,
                        "requested_quantity": line.requested_qty,
                        "reserved_quantity": line.reserved_qty,
                        "outstanding_quantity": line.outstanding_qty,
                    }
                    for line in plan.lines
                ]
                response = {
                    "job_id": job_id,
                    "job_code": job_code,
                    "external_reference": external_reference,
                    "state": "queued",
                    "requested_quantity": plan.requested_quantity,
                    "fulfillable_quantity": plan.fulfillable_quantity,
                    "outstanding_quantity": plan.outstanding_quantity,
                    "items": response_items,
                }
                cursor.execute(
                    """
                    UPDATE operation_events
                    SET actor_worker_id = %s, job_id = %s, payload = %s
                    WHERE event_uuid = %s
                    """,
                    (
                        outbound_order.requested_by,
                        job_id,
                        json.dumps(
                            {
                                "idempotency_key": idempotency_key,
                                "request": fingerprint,
                                "response": response,
                            },
                            ensure_ascii=False,
                        ),
                        event_uuid,
                    ),
                )
                connection.commit()
                return response
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def create_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """Job과 순서 있는 Step, 최초 `job.created` 이벤트를 원자적으로 만든다."""
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

    def assign_job_resources(
        self, job_id: int, assignment: dict[str, Any]
    ) -> dict[str, Any]:
        """Persist one complete revision and reserve all exclusive resources."""
        expected_chargers = {
            "PK_01": "TRIHOUSE-TEST-01-CHG-01",
            "PK_02": "TRIHOUSE-TEST-01-CHG-02",
        }
        revision = int(assignment["revision"])
        response = {"job_id": job_id, **assignment}
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    SELECT job_id, state, context
                    FROM jobs WHERE job_id = %s FOR UPDATE
                    """,
                    (job_id,),
                )
                job = cursor.fetchone()
                if job is None:
                    raise JobNotFound
                context = _json(job.get("context")) or {}
                current = context.get("assignment")
                if current is not None:
                    current_response = {"job_id": job_id, **current}
                    if current_response == response:
                        return current_response
                    if revision <= int(current.get("revision", 0)):
                        raise ResourceAssignmentConflict("ASSIGNMENT_REVISION_CONFLICT")
                    if revision != int(current.get("revision", 0)) + 1:
                        raise ResourceAssignmentConflict("ASSIGNMENT_REVISION_GAP")
                    cursor.execute(
                        """
                        SELECT COUNT(*) AS active_steps FROM job_steps
                        WHERE job_id = %s AND state IN ('running','succeeded')
                        """,
                        (job_id,),
                    )
                    if int(cursor.fetchone()["active_steps"]):
                        raise ResourceAssignmentConflict("ASSIGNMENT_ALREADY_EXECUTING")
                elif revision != 1:
                    raise ResourceAssignmentConflict("INITIAL_ASSIGNMENT_REVISION_MUST_BE_ONE")

                expected_charger = expected_chargers.get(assignment["mobile_id"])
                if expected_charger != assignment["charger_code"]:
                    raise ResourceAssignmentConflict("FIXED_CHARGER_MISMATCH")
                if assignment["packing_dock_code"] == assignment["charger_code"]:
                    raise ResourceAssignmentConflict(
                        "PACKING_DOCK_CHARGER_MUST_DIFFER"
                    )

                device_ids = sorted((assignment["mobile_id"], assignment["omx_id"]))
                cursor.execute(
                    """
                    SELECT device.device_id, device.device_type, device.active,
                           device.control_mode, state.state AS runtime_state,
                           state.health
                    FROM devices device
                    LEFT JOIN device_states state ON state.device_id = device.device_id
                    WHERE device.device_id IN (%s, %s)
                    ORDER BY device.device_id
                    FOR UPDATE
                    """,
                    tuple(device_ids),
                )
                devices = {row["device_id"]: row for row in cursor.fetchall()}
                if set(devices) != set(device_ids):
                    raise ResourceUnavailable("assigned device is not registered")
                if devices[assignment["mobile_id"]]["device_type"] != "mobile":
                    raise ResourceAssignmentConflict("MOBILE_DEVICE_TYPE_MISMATCH")
                if devices[assignment["omx_id"]]["device_type"] != "arm":
                    raise ResourceAssignmentConflict("OMX_DEVICE_TYPE_MISMATCH")
                if any(
                    not row["active"]
                    or row["control_mode"] != "automatic"
                    or row["runtime_state"] not in {"idle", "charging"}
                    or row["health"] != "ok"
                    for row in devices.values()
                ):
                    raise ResourceUnavailable("assigned device is not available")

                location_codes = sorted(
                    (assignment["packing_dock_code"], assignment["charger_code"])
                )
                cursor.execute(
                    """
                    SELECT location_id, location_code, location_type,
                           map_name, state, metadata
                    FROM locations
                    WHERE location_code IN (%s, %s)
                    ORDER BY location_code
                    FOR UPDATE
                    """,
                    tuple(location_codes),
                )
                locations = {row["location_code"]: row for row in cursor.fetchall()}
                if set(locations) != set(location_codes) or any(
                    row["map_name"] != "trihouse_test_01" for row in locations.values()
                ):
                    raise ResourceAssignmentConflict("CANONICAL_MAP_RESOURCE_REQUIRED")
                packing = locations[assignment["packing_dock_code"]]
                charger = locations[assignment["charger_code"]]
                packing_metadata = _json(packing.get("metadata")) or {}
                charger_metadata = _json(charger.get("metadata")) or {}
                cursor.execute(
                    """
                    SELECT manifest FROM map_revisions
                    WHERE map_name = 'trihouse_test_01' AND state = 'published'
                    ORDER BY published_at DESC, map_revision DESC LIMIT 1
                    """
                )
                revision_row = cursor.fetchone()
                manifest = _json(revision_row.get("manifest")) if revision_row else {}
                role_by_code = {
                    waypoint.get("location_code"): waypoint.get("operational_role")
                    for waypoint in (manifest or {}).get("draft_snapshot", {}).get(
                        "waypoints", []
                    )
                }
                packing_role = packing_metadata.get("operational_role") or role_by_code.get(
                    assignment["packing_dock_code"]
                )
                charger_role = charger_metadata.get("operational_role") or role_by_code.get(
                    assignment["charger_code"]
                )
                if packing["location_type"] not in {
                    "outbound_dock",
                    "loading_dock",
                    "staging",
                } or packing_role != "loading_dock":
                    raise ResourceAssignmentConflict("PACKING_DOCK_TYPE_MISMATCH")
                if packing["state"] != "available":
                    raise ResourceAssignmentConflict("PACKING_DOCK_UNAVAILABLE")
                if charger["location_type"] not in {"charger", "staging"} or (
                    charger_role != "charging_station"
                ):
                    raise ResourceAssignmentConflict("CHARGER_TYPE_MISMATCH")
                if charger["state"] != "available":
                    raise ResourceAssignmentConflict("CHARGER_UNAVAILABLE")

                resource_params = (
                    assignment["mobile_id"],
                    assignment["omx_id"],
                    locations[assignment["packing_dock_code"]]["location_id"],
                )
                cursor.execute(
                    """
                    SELECT reservation_id, job_id FROM reservations
                    WHERE state IN ('reserved','in_use')
                      AND (device_id IN (%s, %s) OR location_id = %s)
                    ORDER BY active_resource_key
                    FOR UPDATE
                    """,
                    resource_params,
                )
                conflicts = [
                    row for row in cursor.fetchall() if int(row["job_id"]) != job_id
                ]
                if conflicts:
                    raise ResourceUnavailable("one or more resources are already reserved")

                if current is not None:
                    cursor.execute(
                        """
                        UPDATE reservations
                        SET state = 'released', released_at = NOW(6)
                        WHERE job_id = %s AND state IN ('reserved','in_use')
                        """,
                        (job_id,),
                    )
                context["assignment"] = dict(assignment)
                cursor.execute(
                    """
                    UPDATE jobs
                    SET state = 'assigned', assigned_mobile_id = %s,
                        destination_location_id = %s, context = %s,
                        revision = revision + 1
                    WHERE job_id = %s
                    """,
                    (
                        assignment["mobile_id"],
                        locations[assignment["packing_dock_code"]]["location_id"],
                        json.dumps(context, ensure_ascii=False),
                        job_id,
                    ),
                )
                cursor.execute(
                    """
                    UPDATE job_steps
                    SET assigned_device_id = CASE executor_type
                          WHEN 'mobile' THEN %s WHEN 'arm' THEN %s ELSE NULL END,
                        assignment_revision = %s,
                        target_location_id = CASE WHEN
                          (action_type = 'navigate' AND
                           JSON_UNQUOTE(JSON_EXTRACT(input, '$.branch')) = 'packing_navigate')
                          OR (action_type = 'handover' AND
                              JSON_EXTRACT(input, '$.packing_dock_location_id') IS NOT NULL)
                          OR (action_type = 'wait' AND
                              JSON_UNQUOTE(JSON_EXTRACT(input, '$.wait_for')) = 'worker_completion')
                          THEN %s ELSE target_location_id END,
                        input = CASE WHEN
                          (action_type = 'navigate' AND
                           JSON_UNQUOTE(JSON_EXTRACT(input, '$.branch')) = 'packing_navigate')
                          OR (action_type = 'handover' AND
                              JSON_EXTRACT(input, '$.packing_dock_location_id') IS NOT NULL)
                          OR (action_type = 'wait' AND
                              JSON_UNQUOTE(JSON_EXTRACT(input, '$.wait_for')) = 'worker_completion')
                          THEN JSON_SET(COALESCE(input, JSON_OBJECT()),
                               '$.packing_dock_location_id', %s)
                          ELSE input END
                    WHERE job_id = %s
                    """,
                    (
                        assignment["mobile_id"],
                        assignment["omx_id"],
                        revision,
                        packing["location_id"],
                        packing["location_id"],
                        job_id,
                    ),
                )
                for device_id in sorted(
                    (assignment["mobile_id"], assignment["omx_id"])
                ):
                    cursor.execute(
                        """
                        INSERT INTO reservations
                          (job_id, device_id, reservation_mode, state, expires_at)
                        VALUES (%s, %s, 'exclusive_lock', 'reserved',
                                DATE_ADD(NOW(6), INTERVAL 4 HOUR))
                        """,
                        (job_id, device_id),
                    )
                cursor.execute(
                    """
                    INSERT INTO reservations
                      (job_id, location_id, reservation_mode, state, expires_at)
                    VALUES (%s, %s, 'exclusive_lock', 'reserved',
                            DATE_ADD(NOW(6), INTERVAL 4 HOUR))
                    """,
                    (
                        job_id,
                        locations[assignment["packing_dock_code"]]["location_id"],
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO operation_events
                      (event_uuid, occurred_at, job_id, severity, category,
                       event_type, message, payload)
                    VALUES (%s, NOW(6), %s, 'info', 'policy',
                            'job.assignment.persisted',
                            'Control Tower assignment persisted', %s)
                    """,
                    (
                        str(uuid.uuid4()),
                        job_id,
                        json.dumps({"assignment": assignment}, ensure_ascii=False),
                    ),
                )
                connection.commit()
                return response
            except Exception as error:
                connection.rollback()
                if getattr(error, "errno", None) == 1062:
                    raise ResourceUnavailable(
                        "one or more resources were reserved concurrently"
                    ) from error
                raise
            finally:
                cursor.close()

    def record_load_attempt(
        self, job_step_id: int, request: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        """Append complete load evidence and refresh its restart-safe item projection."""
        event_uuid = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"trihouse:load-attempt:{idempotency_key}")
        )
        command_uuid = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"trihouse:load-command:{idempotency_key}")
        )
        canonical = deepcopy(request)
        response = {
            **canonical,
            "departure_allowed": canonical["result"] == "LOAD_CONFIRMED",
        }
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    SELECT js.job_step_id, js.job_id, js.action_type, js.input,
                           js.assignment_revision, jobs.context,
                           item.job_item_id, item.metadata
                    FROM job_steps js
                    JOIN jobs ON jobs.job_id = js.job_id
                    JOIN job_items item ON item.job_id = js.job_id
                                         AND item.job_item_id = %s
                    WHERE js.job_step_id = %s
                    FOR UPDATE
                    """,
                    (canonical["item_id"], job_step_id),
                )
                row = cursor.fetchone()
                if row is None:
                    raise JobStepNotFound
                cursor.execute(
                    "SELECT parameters FROM job_step_attempts WHERE event_uuid=%s",
                    (event_uuid,),
                )
                replay = cursor.fetchone()
                if replay is not None:
                    parameters = _json(replay["parameters"]) or {}
                    if parameters.get("request") != canonical:
                        raise IdempotencyConflict
                    return parameters["response"]

                step_input = _json(row.get("input")) or {}
                context = _json(row.get("context")) or {}
                assignment = context.get("assignment") or {}
                expected = (
                    int(row["job_id"]),
                    step_input.get("handover_group_id"),
                    int(row["assignment_revision"]),
                    assignment.get("mobile_id"),
                    assignment.get("omx_id"),
                )
                actual = (
                    int(canonical["job_id"]),
                    canonical["handover_group_id"],
                    int(canonical["assignment_revision"]),
                    canonical["pinky_id"],
                    canonical["omx_id"],
                )
                if row["action_type"] != "load" or expected != actual:
                    raise ResourceAssignmentConflict("LOAD_ATTEMPT_IDENTITY_MISMATCH")

                metadata = _json(row.get("metadata")) or {}
                if metadata.get("drop_hold"):
                    raise PickRecoveryConflict("ACTIVE_DROP_HOLD")
                cursor.execute(
                    """
                    SELECT COALESCE(MAX(attempt_no), 0) + 1 AS attempt_no
                    FROM job_step_attempts
                    WHERE job_step_id=%s AND assignment_revision=%s
                      AND actor_role='omx'
                    """,
                    (job_step_id, canonical["assignment_revision"]),
                )
                attempt_no = int(cursor.fetchone()["attempt_no"])
                success = canonical["result"] == "LOAD_CONFIRMED"
                failure_domain = {
                    "LOAD_CONFIRMED": "none",
                    "DROP_DETECTED": "safety",
                    "LOAD_UNCERTAIN": "perception",
                    "GRASP_RETAINED": "manipulation",
                }[canonical["result"]]
                cursor.execute(
                    """
                    INSERT INTO job_step_attempts
                      (attempt_uuid, job_step_id, assignment_revision, actor_role,
                       actor_device_id, attempt_no, event_uuid, command_uuid,
                       state, outcome, success, method_code, outcome_reason_code,
                       failure_domain, parameters, criteria, metrics,
                       before_observation, after_observation, evidence_refs,
                       policy_source, policy_name, policy_version,
                       model_name, model_version, started_at, completed_at)
                    VALUES (%s,%s,%s,'omx',%s,%s,%s,%s,'finished',%s,%s,
                            'OMX_LOAD_CONTRACT_FIXTURE',%s,%s,%s,%s,%s,%s,%s,%s,
                            'rule',%s,%s,%s,%s,NOW(6),NOW(6))
                    """,
                    (
                        canonical["attempt_id"], job_step_id,
                        canonical["assignment_revision"], canonical["omx_id"],
                        attempt_no, event_uuid, command_uuid,
                        "succeeded" if success else "failed", success,
                        canonical["result"], failure_domain,
                        json.dumps(
                            {
                                "record_kind": "load_attempt",
                                "request": canonical,
                                "response": response,
                                "item_id": canonical["item_id"],
                                "handover_group_id": canonical["handover_group_id"],
                                "pinky_id": canonical["pinky_id"],
                                "omx_id": canonical["omx_id"],
                            }, ensure_ascii=False,
                        ),
                        json.dumps(canonical["criteria"], ensure_ascii=False),
                        json.dumps(canonical["metrics"], ensure_ascii=False),
                        json.dumps(canonical["observations"], ensure_ascii=False),
                        json.dumps({"result": canonical["result"]}, ensure_ascii=False),
                        json.dumps(canonical["evidence_refs"], ensure_ascii=False),
                        canonical["policy_name"], canonical["policy_version"],
                        canonical["model_name"], canonical["model_version"],
                    ),
                )
                metadata.update(
                    {
                        "load_result": canonical["result"],
                        "load_attempt_uuid": canonical["attempt_id"],
                        "load_handover_group_id": canonical["handover_group_id"],
                        "load_assignment_revision": canonical["assignment_revision"],
                        "drop_hold": canonical["result"] == "DROP_DETECTED",
                        "object_recovered": False,
                        "area_clear": False,
                    }
                )
                cursor.execute(
                    """
                    UPDATE job_items SET metadata=%s,
                      verification_state=CASE WHEN %s THEN 'matched'
                                              ELSE verification_state END
                    WHERE job_item_id=%s
                    """,
                    (
                        json.dumps(metadata, ensure_ascii=False), success,
                        canonical["item_id"],
                    ),
                )
                connection.commit()
                return response
            except Exception as error:
                connection.rollback()
                if getattr(error, "errno", None) == 1062:
                    raise IdempotencyConflict from error
                raise
            finally:
                cursor.close()

    def record_pick_recovery(
        self, job_step_id: int, request: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        """Persist an operator choice or an explicit DROP-clearance fact."""
        if ("choice" in request) == ("fact" in request):
            raise PickRecoveryConflict("ONE_RECOVERY_ACTION_REQUIRED")
        canonical = deepcopy(request)
        event_uuid = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"trihouse:pick-recovery:{idempotency_key}")
        )
        command_uuid = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"trihouse:recovery-command:{idempotency_key}")
        )
        attempt_uuid = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"trihouse:recovery-attempt:{idempotency_key}")
        )
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    SELECT js.job_id, js.action_type, js.assignment_revision,
                           item.metadata, worker.active AS worker_active
                    FROM job_steps js
                    JOIN job_items item ON item.job_id=js.job_id
                                       AND item.job_item_id=%s
                    LEFT JOIN workers worker ON worker.worker_id=%s
                    WHERE js.job_step_id=%s
                    FOR UPDATE
                    """,
                    (canonical["item_id"], canonical["operator_id"], job_step_id),
                )
                row = cursor.fetchone()
                if row is None or row["action_type"] != "load":
                    raise JobStepNotFound
                cursor.execute(
                    "SELECT parameters FROM job_step_attempts WHERE event_uuid=%s",
                    (event_uuid,),
                )
                replay = cursor.fetchone()
                if replay is not None:
                    parameters = _json(replay["parameters"]) or {}
                    if parameters.get("request") != canonical:
                        raise IdempotencyConflict
                    return parameters["response"]
                if int(row["job_id"]) != int(canonical["job_id"]):
                    raise PickRecoveryConflict("RECOVERY_JOB_MISMATCH")
                if not row.get("worker_active"):
                    raise PickRecoveryConflict("ACTIVE_OPERATOR_REQUIRED")

                metadata = _json(row.get("metadata")) or {}
                retry_no = int(metadata.get("pick_retry_count", 0))
                if "choice" in canonical:
                    if metadata.get("drop_hold"):
                        raise PickRecoveryConflict("ACTIVE_DROP_HOLD")
                    if canonical["choice"] == "재시도":
                        if retry_no >= 2:
                            raise PickRecoveryConflict("RETRY_LIMIT_REACHED")
                        if metadata.get("load_result") not in {
                            "DROP_DETECTED", "LOAD_UNCERTAIN", "GRASP_RETAINED",
                        }:
                            raise PickRecoveryConflict("RETRY_NOT_AVAILABLE")
                        retry_no += 1
                        metadata.update(
                            {
                                "pick_retry_count": retry_no,
                                "reobserve_qr_aruco": True,
                                "act_episode_reset": True,
                                "load_result": None,
                            }
                        )
                        method_code = "PICK_RETRY_SELECTED"
                    elif canonical["choice"] == "포장대에서 처리":
                        metadata["fulfillment_state"] = "MANUAL_FULFILLMENT_REQUIRED"
                        method_code = "MANUAL_FULFILLMENT_REQUIRED"
                    else:
                        raise PickRecoveryConflict("UNSUPPORTED_RECOVERY_CHOICE")
                else:
                    if not metadata.get("drop_hold"):
                        raise PickRecoveryConflict("NO_ACTIVE_DROP_HOLD")
                    if canonical["fact"] == "object-recovered":
                        metadata["object_recovered"] = True
                        method_code = "DROP_OBJECT_RECOVERED"
                    elif canonical["fact"] == "area-clear":
                        metadata["area_clear"] = True
                        method_code = "DROP_AREA_CLEAR"
                    else:
                        raise PickRecoveryConflict("UNSUPPORTED_RECOVERY_FACT")
                    metadata["drop_hold"] = not (
                        metadata.get("object_recovered") and metadata.get("area_clear")
                    )

                response = {
                    "job_id": int(canonical["job_id"]),
                    "item_id": int(canonical["item_id"]),
                    "retry_no": retry_no,
                    "drop_hold": bool(metadata.get("drop_hold")),
                    "manual_required": metadata.get("fulfillment_state")
                    == "MANUAL_FULFILLMENT_REQUIRED",
                    "reobserve_qr_aruco": bool(metadata.get("reobserve_qr_aruco")),
                    "reset_act_episode": bool(metadata.get("act_episode_reset")),
                }
                cursor.execute(
                    """
                    SELECT COALESCE(MAX(attempt_no),0)+1 AS attempt_no
                    FROM job_step_attempts
                    WHERE job_step_id=%s AND assignment_revision=%s
                      AND actor_role='fms'
                    """,
                    (job_step_id, row["assignment_revision"]),
                )
                attempt_no = int(cursor.fetchone()["attempt_no"])
                cursor.execute(
                    """
                    INSERT INTO job_step_attempts
                      (attempt_uuid, job_step_id, assignment_revision, actor_role,
                       attempt_no, event_uuid, command_uuid, state, outcome, success,
                       method_code, outcome_reason_code, failure_domain, parameters,
                       criteria, metrics, before_observation, after_observation,
                       evidence_refs, policy_source, policy_name, policy_version,
                       started_at, completed_at)
                    VALUES (%s,%s,%s,'fms',%s,%s,%s,'finished','succeeded',TRUE,
                            %s,%s,'none',%s,%s,%s,%s,%s,%s,'operator',
                            'pick-recovery-contract','1',NOW(6),NOW(6))
                    """,
                    (
                        attempt_uuid, job_step_id, row["assignment_revision"],
                        attempt_no, event_uuid, command_uuid, method_code, method_code,
                        json.dumps(
                            {
                                "record_kind": "pick_recovery",
                                "request": canonical,
                                "response": response,
                            }, ensure_ascii=False,
                        ),
                        json.dumps({"operator_action_explicit": True}),
                        json.dumps({"retry_no": retry_no}),
                        json.dumps({"load_result": metadata.get("load_result")}),
                        json.dumps(metadata, ensure_ascii=False),
                        json.dumps([], ensure_ascii=False),
                    ),
                )
                cursor.execute(
                    """
                    UPDATE job_items SET metadata=%s,
                      verification_state=CASE WHEN %s THEN 'manual_review'
                                              ELSE verification_state END
                    WHERE job_item_id=%s
                    """,
                    (
                        json.dumps(metadata, ensure_ascii=False),
                        response["manual_required"], canonical["item_id"],
                    ),
                )
                connection.commit()
                return response
            except Exception as error:
                connection.rollback()
                if getattr(error, "errno", None) == 1062:
                    raise IdempotencyConflict from error
                raise
            finally:
                cursor.close()

    @staticmethod
    def _job_detail_from_cursor(cursor, job_id: int) -> dict[str, Any] | None:
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
            SELECT job_item_id, product_code, requested_qty, completed_qty,
                   lot_id, handling_unit_code, verification_state, metadata
            FROM job_items WHERE job_id = %s ORDER BY job_item_id
            """,
            (job_id,),
        )
        items = []
        for item_row in cursor.fetchall():
            item = dict(item_row)
            item["metadata"] = _json(item.get("metadata")) or {}
            items.append(item)
        job["items"] = items
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

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                return self._job_detail_from_cursor(cursor, job_id)
            finally:
                cursor.close()

    def complete_worker_packing(
        self, job_id: int, request: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        """Finalize physical stock and enqueue the fixed return in one transaction."""
        canonical_request = {
            "worker_id": request["worker_id"],
            "completion_note": request.get("completion_note"),
            "acknowledged_manual_item_ids": sorted(
                set(request.get("acknowledged_manual_item_ids", []))
            ),
        }
        fingerprint = {"job_id": job_id, "request": canonical_request}
        event_uuid = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"trihouse:worker-completion:{idempotency_key}",
            )
        )
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                # Global lock order: Job -> relevant Steps -> Items -> lots -> ledger.
                cursor.execute(
                    """
                    SELECT job_id, state, assigned_mobile_id,
                           destination_location_id, context
                    FROM jobs WHERE job_id = %s FOR UPDATE
                    """,
                    (job_id,),
                )
                job = cursor.fetchone()
                if job is None:
                    raise JobNotFound
                cursor.execute(
                    "SELECT payload FROM operation_events WHERE event_uuid = %s",
                    (event_uuid,),
                )
                replay_event = cursor.fetchone()
                if replay_event is not None:
                    replay_payload = _json(replay_event["payload"]) or {}
                    if replay_payload.get("request") != fingerprint:
                        raise IdempotencyConflict
                    if replay_payload.get("response") is None:
                        raise RuntimeError(
                            "completion idempotency response was not committed"
                        )
                    return replay_payload["response"]
                context = _json(job.get("context")) or {}
                assignment = context.get("assignment") or {}
                if not assignment:
                    raise WorkerCompletionConflict("ASSIGNMENT_REQUIRED")

                cursor.execute(
                    "SELECT active FROM workers WHERE worker_id = %s",
                    (canonical_request["worker_id"],),
                )
                worker = cursor.fetchone()
                if worker is None or not worker["active"]:
                    raise WorkerCompletionConflict("ACTIVE_WORKER_REQUIRED")

                cursor.execute(
                    """
                    INSERT IGNORE INTO operation_events
                      (event_uuid, occurred_at, actor_worker_id, job_id,
                       severity, category, event_type, message, payload)
                    VALUES (%s, NOW(6), %s, %s, 'info', 'inventory',
                            'worker.packing.completed',
                            'worker completed outbound packing', %s)
                    """,
                    (
                        event_uuid,
                        canonical_request["worker_id"],
                        job_id,
                        json.dumps(
                            {"request": fingerprint, "response": None},
                            ensure_ascii=False,
                        ),
                    ),
                )
                owns_key = cursor.rowcount == 1
                if not owns_key:
                    cursor.execute(
                        "SELECT payload FROM operation_events WHERE event_uuid = %s",
                        (event_uuid,),
                    )
                    existing = cursor.fetchone()
                    if existing is None:
                        raise RuntimeError("completion idempotency event was not readable")
                    payload = _json(existing["payload"]) or {}
                    if payload.get("request") != fingerprint:
                        raise IdempotencyConflict
                    if payload.get("response") is None:
                        raise RuntimeError("completion idempotency response was not committed")
                    return payload["response"]

                cursor.execute(
                    """
                    SELECT job_step_id, step_no, action_type,
                           target_location_id, state, input,
                           assigned_device_id, assignment_revision
                    FROM job_steps
                    WHERE job_id = %s
                      AND action_type IN ('handover','wait','return_home')
                    ORDER BY step_no
                    FOR UPDATE
                    """,
                    (job_id,),
                )
                steps = [dict(row) for row in cursor.fetchall()]
                packing_handover = [
                    step
                    for step in steps
                    if step["action_type"] == "handover"
                    and step["target_location_id"] == job["destination_location_id"]
                ]
                waits = [step for step in steps if step["action_type"] == "wait"]
                returns = [
                    step for step in steps if step["action_type"] == "return_home"
                ]
                if (
                    len(packing_handover) != 1
                    or packing_handover[0]["state"] != "succeeded"
                    or len(waits) != 1
                    or waits[0]["state"] not in {"pending", "running"}
                    or len(returns) != 1
                    or returns[0]["state"] != "pending"
                ):
                    raise WorkerCompletionConflict("PACKING_NOT_READY")
                wait_step = waits[0]
                return_step = returns[0]

                cursor.execute(
                    """
                    SELECT job_item_id, product_code, requested_qty,
                           completed_qty, lot_id, verification_state, metadata
                    FROM job_items WHERE job_id = %s
                    ORDER BY job_item_id
                    FOR UPDATE
                    """,
                    (job_id,),
                )
                items = []
                for row in cursor.fetchall():
                    item = dict(row)
                    item["metadata"] = _json(item.get("metadata")) or {}
                    items.append(item)
                lot_ids = sorted(
                    {int(item["lot_id"]) for item in items if item["lot_id"] is not None}
                )
                lots: dict[int, dict[str, Any]] = {}
                if lot_ids:
                    placeholders = ", ".join(["%s"] * len(lot_ids))
                    cursor.execute(
                        f"""
                        SELECT lot_id, available_qty, reserved_qty
                        FROM inventory_lots
                        WHERE lot_id IN ({placeholders})
                        ORDER BY lot_id
                        FOR UPDATE
                        """,
                        tuple(lot_ids),
                    )
                    lots = {
                        int(row["lot_id"]): dict(row) for row in cursor.fetchall()
                    }
                cursor.execute(
                    """
                    SELECT reservation_id, location_id, device_id, state
                    FROM reservations WHERE job_id = %s
                    ORDER BY reservation_id
                    FOR UPDATE
                    """,
                    (job_id,),
                )
                reservations = [dict(row) for row in cursor.fetchall()]

                cursor.execute(
                    """
                    SELECT attempt.outcome_reason_code, attempt.parameters
                    FROM job_step_attempts attempt
                    JOIN job_steps step ON step.job_step_id=attempt.job_step_id
                    WHERE step.job_id=%s
                    ORDER BY attempt.attempt_uuid
                    FOR UPDATE
                    """,
                    (job_id,),
                )
                attempt_rows = [dict(row) for row in cursor.fetchall()]
                confirmed_item_ids: set[int] = set()
                manual_item_ids: set[int] = set()
                for attempt in attempt_rows:
                    parameters = _json(attempt.get("parameters")) or {}
                    item_id = parameters.get("item_id") or parameters.get(
                        "request", {}
                    ).get("item_id")
                    if item_id is None:
                        continue
                    if attempt["outcome_reason_code"] == "LOAD_CONFIRMED":
                        confirmed_item_ids.add(int(item_id))
                    if attempt["outcome_reason_code"] == "MANUAL_FULFILLMENT_REQUIRED":
                        manual_item_ids.add(int(item_id))

                if any(item["metadata"].get("drop_hold") for item in items):
                    raise WorkerCompletionConflict("ACTIVE_DROP_HOLD")
                for item in items:
                    item_id = int(item["job_item_id"])
                    metadata = item["metadata"]
                    load_confirmed = (
                        metadata.get("load_result") == "LOAD_CONFIRMED"
                        and item_id in confirmed_item_ids
                    )
                    manual_required = (
                        metadata.get("fulfillment_state")
                        == "MANUAL_FULFILLMENT_REQUIRED"
                        and item_id in manual_item_ids
                    )
                    if not (load_confirmed or manual_required):
                        raise WorkerCompletionConflict("LOAD_CONFIRMATION_REQUIRED")

                manual_ids = tuple(
                    int(item["job_item_id"])
                    for item in items
                    if item["verification_state"] == "manual_review"
                    or item["metadata"].get("fulfillment_state")
                    == "MANUAL_FULFILLMENT_REQUIRED"
                )
                acknowledged = set(
                    canonical_request["acknowledged_manual_item_ids"]
                )
                missing = tuple(item_id for item_id in manual_ids if item_id not in acknowledged)
                if missing:
                    raise ManualAcknowledgementRequired(missing)
                known_item_ids = {int(item["job_item_id"]) for item in items}
                if not acknowledged <= known_item_ids:
                    raise WorkerCompletionConflict("UNKNOWN_ITEM_ACKNOWLEDGEMENT")

                required_by_lot: dict[int, int] = {}
                completed_by_item: dict[int, int] = {}
                for item in items:
                    reserved_quantity = int(
                        item["metadata"].get("reserved_quantity", 0)
                    )
                    completed_by_item[int(item["job_item_id"])] = reserved_quantity
                    if item["lot_id"] is not None and reserved_quantity:
                        lot_id = int(item["lot_id"])
                        required_by_lot[lot_id] = (
                            required_by_lot.get(lot_id, 0) + reserved_quantity
                        )
                if set(required_by_lot) - set(lots):
                    raise WorkerCompletionConflict("INVENTORY_LOT_MISSING")
                for lot_id, quantity in sorted(required_by_lot.items()):
                    lot = lots[lot_id]
                    if (
                        int(lot["available_qty"]) < quantity
                        or int(lot["reserved_qty"]) < quantity
                    ):
                        raise WorkerCompletionConflict("INVENTORY_RESERVATION_MISMATCH")

                for item in items:
                    cursor.execute(
                        """
                        UPDATE job_items
                        SET completed_qty = %s,
                            verification_state = CASE
                              WHEN verification_state = 'manual_review'
                              THEN 'matched' ELSE verification_state END,
                            metadata = JSON_SET(
                              COALESCE(metadata, JSON_OBJECT()),
                              '$.worker_completion_acknowledged', true
                            )
                        WHERE job_item_id = %s
                        """,
                        (
                            completed_by_item[int(item["job_item_id"])],
                            item["job_item_id"],
                        ),
                    )
                for lot_id, quantity in sorted(required_by_lot.items()):
                    lot = lots[lot_id]
                    available_after = int(lot["available_qty"]) - quantity
                    reserved_after = int(lot["reserved_qty"]) - quantity
                    cursor.execute(
                        """
                        UPDATE inventory_lots
                        SET available_qty = %s, reserved_qty = %s
                        WHERE lot_id = %s
                        """,
                        (available_after, reserved_after, lot_id),
                    )
                    cursor.execute(
                        """
                        INSERT INTO inventory_moves
                          (lot_id, job_id, job_step_id, move_type,
                           quantity_delta, quantity_after, reserved_delta,
                           reserved_after, recorded_by, note)
                        VALUES (%s, %s, %s, 'outbound', %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            lot_id,
                            job_id,
                            wait_step["job_step_id"],
                            -quantity,
                            available_after,
                            -quantity,
                            reserved_after,
                            canonical_request["worker_id"],
                            canonical_request["completion_note"],
                        ),
                    )

                active_packing = [
                    reservation
                    for reservation in reservations
                    if reservation["location_id"] == job["destination_location_id"]
                    and reservation["state"] in {"reserved", "in_use"}
                ]
                if len(active_packing) != 1:
                    raise WorkerCompletionConflict("PACKING_RESERVATION_MISMATCH")
                cursor.execute(
                    """
                    UPDATE reservations
                    SET state = 'released', released_at = NOW(6)
                    WHERE reservation_id = %s
                    """,
                    (active_packing[0]["reservation_id"],),
                )
                cursor.execute(
                    """
                    UPDATE job_steps
                    SET state = 'succeeded', completed_at = NOW(6),
                        result = %s
                    WHERE job_step_id = %s
                    """,
                    (
                        json.dumps(
                            {
                                "worker_id": canonical_request["worker_id"],
                                "manual_item_acknowledgements": sorted(acknowledged),
                            },
                            ensure_ascii=False,
                        ),
                        wait_step["job_step_id"],
                    ),
                )

                charger_code = assignment.get("charger_code")
                expected_charger = {
                    "PK_01": "TRIHOUSE-TEST-01-CHG-01",
                    "PK_02": "TRIHOUSE-TEST-01-CHG-02",
                }.get(job["assigned_mobile_id"])
                if charger_code != expected_charger:
                    raise WorkerCompletionConflict("FIXED_CHARGER_MISMATCH")
                cursor.execute(
                    """
                    SELECT location_id FROM locations
                    WHERE location_code = %s AND map_name = 'trihouse_test_01'
                    """,
                    (charger_code,),
                )
                charger = cursor.fetchone()
                if charger is None:
                    raise WorkerCompletionConflict("FIXED_CHARGER_NOT_FOUND")
                assignment_revision = int(assignment["revision"])
                cursor.execute(
                    """
                    UPDATE job_steps
                    SET target_location_id = %s, assigned_device_id = %s,
                        assignment_revision = %s,
                        input = JSON_SET(
                          COALESCE(input, JSON_OBJECT()),
                          '$.charger_code', %s,
                          '$.assignment_revision', %s
                        )
                    WHERE job_step_id = %s
                    """,
                    (
                        charger["location_id"],
                        job["assigned_mobile_id"],
                        assignment_revision,
                        charger_code,
                        assignment_revision,
                        return_step["job_step_id"],
                    ),
                )
                return_key = (
                    f"worker-completion:{job_id}:revision:{assignment_revision}:return-home"
                )
                return_payload = {
                    "job_id": job_id,
                    "job_step_id": int(return_step["job_step_id"]),
                    "action_type": "return_home",
                    "assigned_mobile_id": job["assigned_mobile_id"],
                    "assignment_revision": assignment_revision,
                    "charger_code": charger_code,
                    "target_location_id": int(charger["location_id"]),
                }
                cursor.execute(
                    """
                    INSERT INTO integration_messages
                      (message_id, direction, channel, device_id, job_step_id,
                       message_type, idempotency_key, payload)
                    VALUES (%s, 'outbound', 'rmf', %s, %s, %s, %s, %s)
                    """,
                    (
                        str(uuid.uuid4()),
                        job["assigned_mobile_id"],
                        return_step["job_step_id"],
                        "return_home",
                        return_key,
                        json.dumps(return_payload, ensure_ascii=False),
                    ),
                )
                cursor.execute(
                    """
                    UPDATE jobs
                    SET state = 'running',
                        state_reason_code = 'RETURNING_TO_FIXED_CHARGER'
                    WHERE job_id = %s
                    """,
                    (job_id,),
                )
                response = self._job_detail_from_cursor(cursor, job_id)
                assert response is not None
                safe_response = _json_safe(response)
                cursor.execute(
                    """
                    UPDATE operation_events SET payload = %s
                    WHERE event_uuid = %s
                    """,
                    (
                        json.dumps(
                            {"request": fingerprint, "response": safe_response},
                            ensure_ascii=False,
                        ),
                        event_uuid,
                    ),
                )
                connection.commit()
                return safe_response
            except Exception:
                connection.rollback()
                raise
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
        """현재 실행 가능한 Step을 멱등 outbox 메시지로 만든다.

        앞 Step의 성공 여부, retry 상태, 기존 활성 dispatch를 잠금 아래 확인해
        하나의 Step이 중복 실행자에게 전달되지 않도록 한다.
        """
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    SELECT js.job_step_id, js.job_id, js.step_no, js.executor_type,
                           js.action_type, js.target_location_id, js.state, js.input,
                           js.assigned_device_id, js.assignment_revision,
                           jobs.context AS job_context
                    FROM job_steps js
                    JOIN jobs ON jobs.job_id = js.job_id
                    WHERE js.job_step_id = %s
                    FOR UPDATE
                    """,
                    (job_step_id,),
                )
                step = cursor.fetchone()
                if step is None:
                    raise JobStepNotFound
                job_context = _json(step.get("job_context")) or {}
                if (
                    job_context.get("source") == "public_product_order"
                    and not job_context.get("assignment")
                ):
                    raise JobStepNotDispatchable
                requested_device = request.get("assigned_device_id")
                if (
                    step.get("assigned_device_id") is not None
                    and requested_device is not None
                    and requested_device != step["assigned_device_id"]
                ):
                    raise ResourceAssignmentConflict(
                        "DISPATCH_ASSIGNED_DEVICE_MISMATCH"
                    )
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
                cursor.execute(
                    """
                    SELECT item.job_item_id, item.metadata
                    FROM job_items item
                    JOIN inventory_lots lot ON lot.lot_id=item.lot_id
                    WHERE item.job_id=%s AND EXISTS (
                      SELECT 1 FROM job_steps load_step
                      WHERE load_step.job_id=item.job_id
                        AND load_step.action_type='load'
                        AND load_step.step_no < %s
                        AND JSON_UNQUOTE(JSON_EXTRACT(load_step.input, '$.temperature_zone'))
                            = lot.temperature_zone
                    )
                    ORDER BY item.job_item_id
                    FOR UPDATE
                    """,
                    (step["job_id"], step["step_no"]),
                )
                gated_items = [dict(row) for row in cursor.fetchall()]
                if gated_items:
                    cursor.execute(
                        """
                        SELECT attempt.outcome_reason_code, attempt.parameters
                        FROM job_step_attempts attempt
                        JOIN job_steps attempted_step
                          ON attempted_step.job_step_id=attempt.job_step_id
                        WHERE attempted_step.job_id=%s
                        ORDER BY attempt.attempt_uuid
                        FOR UPDATE
                        """,
                        (step["job_id"],),
                    )
                    load_confirmed: set[int] = set()
                    manual_required: set[int] = set()
                    for attempt in cursor.fetchall():
                        parameters = _json(attempt.get("parameters")) or {}
                        item_id = parameters.get("item_id") or parameters.get(
                            "request", {}
                        ).get("item_id")
                        if item_id is None:
                            continue
                        if attempt["outcome_reason_code"] == "LOAD_CONFIRMED":
                            load_confirmed.add(int(item_id))
                        if attempt["outcome_reason_code"] == "MANUAL_FULFILLMENT_REQUIRED":
                            manual_required.add(int(item_id))
                    for item in gated_items:
                        item_id = int(item["job_item_id"])
                        metadata = _json(item.get("metadata")) or {}
                        if metadata.get("drop_hold"):
                            raise JobStepNotDispatchable
                        if not (
                            metadata.get("load_result") == "LOAD_CONFIRMED"
                            and item_id in load_confirmed
                        ) and not (
                            metadata.get("fulfillment_state")
                            == "MANUAL_FULFILLMENT_REQUIRED"
                            and item_id in manual_required
                        ):
                            raise JobStepNotDispatchable
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
                        step.get("assigned_device_id") or requested_device,
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
        """`SKIP LOCKED`로 여러 RMF worker가 서로 다른 pending 메시지를 선점한다."""
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
        """RMF 수락과 task/device 배정을 기록한다.

        동일 결과 재전송은 허용하되 기존 배정과 다른 재전송은 충돌로 처리한다.
        """
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    SELECT im.message_id, im.job_step_id, im.state,
                           im.external_reference,
                           js.rmf_task_id, js.assigned_device_id,
                           js.executor_type, jobs.assigned_mobile_id
                    FROM integration_messages im
                    JOIN job_steps js ON js.job_step_id = im.job_step_id
                    JOIN jobs ON jobs.job_id = js.job_id
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
                if (
                    acceptance["accepted"]
                    and message["executor_type"] == "mobile"
                    and message["assigned_mobile_id"] is not None
                    and acceptance["assigned_device_id"]
                    != message["assigned_mobile_id"]
                ):
                    raise ResourceAssignmentConflict(
                        "RMF_ASSIGNED_DEVICE_MISMATCH"
                    )
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
                    if message["assigned_mobile_id"] is not None:
                        cursor.execute(
                            """
                            UPDATE job_steps SET rmf_task_id = %s
                            WHERE job_step_id = %s
                            """,
                            (acceptance["rmf_task_id"], message["job_step_id"]),
                        )
                    else:
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
        """RMF 배정과 robot identity를 확인하고 실행용 task_context를 발급한다."""
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
    """API 경계와 상태 전이 단위 테스트용 결정적 메모리 구현.

    SQL을 흉내 내기보다 운영 Repository의 외부 결과와 충돌 규칙을 재현한다.
    실제 잠금과 스키마의 검증은 MySQL integration test가 담당한다.
    """

    def __init__(self, seed_locations: list[dict[str, Any]] | None = None):
        self._jobs: dict[int, dict[str, Any]] = {}
        self._steps: dict[int, dict[str, Any]] = {}
        self._events: dict[int, list[dict[str, Any]]] = {}
        self._dispatches: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        self._claims: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
        self._reserved_assignment_resources: dict[str, int] = {}
        self._assignment_lock = threading.RLock()
        self._assignment_locations: dict[str, dict[str, Any]] = {
            "PACKING-01-DOCK-01": {
                "location_id": 1,
                "location_type": "outbound_dock",
                "state": "available",
                "operational_role": "loading_dock",
            },
            "PACKING-01-DOCK-02": {
                "location_id": 2,
                "location_type": "outbound_dock",
                "state": "available",
                "operational_role": "loading_dock",
            },
            "TRIHOUSE-TEST-01-CHG-01": {
                "location_id": 3,
                "location_type": "charger",
                "state": "available",
                "operational_role": "charging_station",
            },
            "TRIHOUSE-TEST-01-CHG-02": {
                "location_id": 4,
                "location_type": "charger",
                "state": "available",
                "operational_role": "charging_station",
            },
        }
        self._next_job_id = 1
        self._next_step_id = 1
        self._next_event_id = 1
        self._operation_events: list[dict[str, Any]] = []
        self._device_states: dict[str, dict[str, Any]] = {}
        self._task_events: dict[str, dict[str, Any]] = {}
        self._map_projects: dict[str, dict[str, Any]] = {}
        self._map_publish_lock = threading.RLock()
        self._map_project_sources: dict[str, dict[str, dict[str, Any]]] = {}
        self._map_publications: dict[str, dict[str, Any]] = {}
        self._map_publications_by_revision: dict[str, dict[str, Any]] = {}
        self._locations: dict[str, dict[str, Any]] = {
            location["location_code"]: deepcopy(location)
            for location in (seed_locations or [])
        }
        self._map_features: dict[str, list[dict[str, Any]]] = {}
        self._next_location_id = (
            max(
                (int(location.get("location_id", 0)) for location in self._locations.values()),
                default=0,
            )
            + 1
        )

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
        with self._map_publish_lock:
            return self._save_public_map_draft_locked(
                map_name, draft, expected_revision, staged_sources
            )

    def _save_public_map_draft_locked(
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
        return [
            deepcopy(event)
            for event in self._operation_events
            if event.get("event_type") == "MAP_DEPLOYMENT_FAILED"
            and event.get("payload", {}).get("map_name") == map_name
        ]

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
        with self._map_publish_lock:
            snapshots = (
                deepcopy(self._map_publications),
                deepcopy(self._map_publications_by_revision),
                deepcopy(self._locations),
                deepcopy(self._map_features),
                self._next_location_id,
            )
            try:
                return self._publish_map_project_locked(map_name, publication)
            except Exception:
                (
                    self._map_publications,
                    self._map_publications_by_revision,
                    self._locations,
                    self._map_features,
                    self._next_location_id,
                ) = snapshots
                raise

    def _publish_map_project_locked(
        self, map_name: str, publication: dict[str, Any]
    ) -> dict[str, Any]:
        project = self._map_projects.get(map_name)
        if project is None:
            raise MapProjectNotFound
        if not publication["map_revision"].startswith(f"{map_name}:"):
            raise MapRevisionContentConflict
        _assert_publication_expectations(
            _public_draft_from_project(self.get_map_project(map_name)),
            publication,
            lambda source_type, source_uuid: self._map_project_sources.get(
                map_name, {}
            ).get(str(source_uuid)),
        )
        existing_by_revision = self._map_publications_by_revision.get(
            publication["map_revision"]
        )
        if existing_by_revision:
            identity = _publication_identity(map_name, publication)
            existing_identity = _publication_identity(
                existing_by_revision["map_name"], existing_by_revision
            )
            if existing_identity != identity:
                raise MapRevisionContentConflict
            return deepcopy(existing_by_revision)
        errors = _validate_map_draft(project)
        if errors:
            raise MapProjectValidationError(errors)
        errors = _validate_publication_artifacts(project, publication)
        if errors:
            raise MapProjectValidationError(errors)
        for waypoint in project["payload"].get("waypoints", []):
            location_code = waypoint.get("locationCode")
            if not location_code:
                continue
            projection = _waypoint_projection(waypoint)
            if not projection["project_location"]:
                continue
            parent_location_id = None
            parent_location_code = projection["parent_location_code"]
            if parent_location_code:
                parent = self._locations.get(parent_location_code)
                if parent is None:
                    raise MapProjectValidationError(
                        [f"{location_code}: parentLocationCode가 존재하지 않습니다"]
                    )
                parent_location_id = parent["location_id"]
            existing_location = self._locations.get(location_code)
            if (
                existing_location
                and existing_location.get("map_name") is not None
                and existing_location.get("map_name") != map_name
            ):
                raise MapProjectValidationError(
                    [f"{location_code}: 다른 published map이 소유합니다"]
                )
            location_type = projection["location_type"]
            if (
                projection["operational_role"] is None
                and projection["category"] == "pickup"
                and existing_location
            ):
                location_type = existing_location["location_type"]
            map_pose = waypoint["mapPose"]
            location_id = (
                existing_location["location_id"]
                if existing_location
                else self._next_location_id
            )
            if existing_location is None:
                self._next_location_id += 1
            self._locations[location_code] = {
                "location_id": location_id,
                "parent_location_id": parent_location_id,
                "location_code": location_code,
                "name": waypoint.get("name") or waypoint["rmfWaypointName"],
                "location_type": location_type,
                "temperature_zone": projection["temperature_zone"],
                "map_name": map_name,
                "rmf_waypoint_name": waypoint["rmfWaypointName"],
                "pose_x": float(map_pose[0]),
                "pose_y": float(map_pose[1]),
                "pose_yaw": float(map_pose[2]),
                "metadata": {
                    "authoring_managed": True,
                    "active": True,
                    "waypoint_uuid": waypoint["waypointUuid"],
                    "map_revision": publication["map_revision"],
                    "operational_role": projection["operational_role"],
                    "rmf_category": projection["category"],
                    "parent_location_code": parent_location_code,
                },
            }
        projected_features = [
            _bottleneck_projection(map_name, publication["map_revision"], zone)
            for zone in project["payload"].get("bottleneckZones", [])
        ]
        for binding in project["payload"].get("fiducialBindings", []):
            location = self._locations.get(binding["targetLocationCode"])
            projected_features.append(
                _fiducial_projection(
                    map_name,
                    publication["map_revision"],
                    binding,
                    int(location["location_id"]) if location else None,
                )
            )
        self._map_features[publication["map_revision"]] = projected_features
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

    def get_projected_location(self, location_code: str) -> dict[str, Any] | None:
        location = self._locations.get(location_code)
        return deepcopy(location) if location else None

    def list_projected_map_features(self, map_revision: str) -> list[dict[str, Any]]:
        return deepcopy(self._map_features.get(map_revision, []))

    def record_map_project_changes(
        self, map_name: str, changes: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if map_name not in self._map_projects:
            raise MapProjectNotFound
        events: list[dict[str, Any]] = []
        for change in changes:
            event = {
                "event_id": self._next_event_id,
                "event_uuid": str(uuid.uuid4()),
                "occurred_at": datetime.now(SEOUL),
                "actor_worker_id": None,
                "device_id": None,
                "job_id": None,
                "job_step_id": None,
                "incident_id": None,
                "severity": "info",
                "category": "system",
                "event_type": "MAP_PROJECT_CHANGED",
                "message": change["summary"],
                "payload": {"map_name": map_name, "change": deepcopy(change)},
            }
            self._next_event_id += 1
            self._operation_events.append(event)
            events.append(deepcopy(event))
        return events

    def list_operation_events(
        self,
        from_at: datetime | None,
        to_at: datetime | None,
        limit: int,
        before_at: datetime | None = None,
        before_event_id: int | None = None,
    ) -> list[dict[str, Any]]:
        if from_at is not None and from_at.tzinfo is None:
            from_at = from_at.replace(tzinfo=SEOUL)
        if to_at is not None and to_at.tzinfo is None:
            to_at = to_at.replace(tzinfo=SEOUL)
        if before_at is not None and before_at.tzinfo is None:
            before_at = before_at.replace(tzinfo=SEOUL)
        events = (
            event
            for event in self._operation_events
            if (from_at is None or event["occurred_at"] >= from_at)
            and (to_at is None or event["occurred_at"] < to_at)
            and (
                before_at is None
                or before_event_id is None
                or event["occurred_at"] < before_at
                or (
                    event["occurred_at"] == before_at
                    and event["event_id"] < before_event_id
                )
            )
        )
        ordered = sorted(
            events,
            key=lambda event: (event["occurred_at"], event["event_id"]),
            reverse=True,
        )
        return deepcopy(ordered[:limit])

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
        detail.setdefault("items", [])
        detail["steps"] = [deepcopy(step) for step in sorted(self._steps.values(), key=lambda row: row["step_no"]) if step["job_id"] == job_id]
        return detail

    def assign_job_resources(
        self, job_id: int, assignment: dict[str, Any]
    ) -> dict[str, Any]:
        with self._assignment_lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFound
            expected = {
                "PK_01": "TRIHOUSE-TEST-01-CHG-01",
                "PK_02": "TRIHOUSE-TEST-01-CHG-02",
            }.get(assignment["mobile_id"])
            if expected != assignment["charger_code"]:
                raise ResourceAssignmentConflict("FIXED_CHARGER_MISMATCH")
            if assignment["packing_dock_code"] == assignment["charger_code"]:
                raise ResourceAssignmentConflict("PACKING_DOCK_CHARGER_MUST_DIFFER")
            packing = self._assignment_locations.get(assignment["packing_dock_code"])
            charger = self._assignment_locations.get(assignment["charger_code"])
            if packing is None or charger is None:
                raise ResourceAssignmentConflict("CANONICAL_MAP_RESOURCE_REQUIRED")
            if packing["location_type"] not in {"outbound_dock", "loading_dock"} or packing.get(
                "operational_role"
            ) not in {None, "loading_dock"}:
                raise ResourceAssignmentConflict("PACKING_DOCK_TYPE_MISMATCH")
            if packing["state"] != "available":
                raise ResourceAssignmentConflict("PACKING_DOCK_UNAVAILABLE")
            if charger["location_type"] != "charger" or charger.get(
                "operational_role"
            ) not in {None, "charging_station"}:
                raise ResourceAssignmentConflict("CHARGER_TYPE_MISMATCH")
            if charger["state"] != "available":
                raise ResourceAssignmentConflict("CHARGER_UNAVAILABLE")

            context = job.setdefault("context", {})
            current = context.get("assignment")
            response = {"job_id": job_id, **deepcopy(assignment)}
            if current is not None:
                if {"job_id": job_id, **current} == response:
                    return response
                current_revision = int(current["revision"])
                revision = int(assignment["revision"])
                if revision <= current_revision:
                    raise ResourceAssignmentConflict("ASSIGNMENT_REVISION_CONFLICT")
                if revision != current_revision + 1:
                    raise ResourceAssignmentConflict("ASSIGNMENT_REVISION_GAP")
                if any(
                    step["job_id"] == job_id
                    and step["state"] in {"running", "succeeded"}
                    for step in self._steps.values()
                ):
                    raise ResourceAssignmentConflict("ASSIGNMENT_ALREADY_EXECUTING")
            elif int(assignment["revision"]) != 1:
                raise ResourceAssignmentConflict("INITIAL_ASSIGNMENT_REVISION_MUST_BE_ONE")

            resources = (
                assignment["mobile_id"],
                assignment["omx_id"],
                assignment["packing_dock_code"],
            )
            if any(
                resource in self._reserved_assignment_resources
                and self._reserved_assignment_resources[resource] != job_id
                for resource in resources
            ):
                raise ResourceUnavailable("one or more resources are already reserved")

            if current is not None:
                for value in (
                    current["mobile_id"],
                    current["omx_id"],
                    current["packing_dock_code"],
                ):
                    if self._reserved_assignment_resources.get(value) == job_id:
                        self._reserved_assignment_resources.pop(value)
            for resource in resources:
                self._reserved_assignment_resources[resource] = job_id
            context["assignment"] = deepcopy(assignment)
            job["assigned_mobile_id"] = assignment["mobile_id"]
            job["destination_location_id"] = packing["location_id"]
            job["state"] = "assigned"
            for step in self._steps.values():
                if step["job_id"] != job_id:
                    continue
                step["assignment_revision"] = int(assignment["revision"])
                step["assigned_device_id"] = {
                    "mobile": assignment["mobile_id"],
                    "arm": assignment["omx_id"],
                }.get(step["executor_type"])
                payload = step.get("input") or {}
                is_packing = (
                    step["action_type"] == "navigate"
                    and payload.get("branch") == "packing_navigate"
                ) or (
                    step["action_type"] == "handover"
                    and "packing_dock_location_id" in payload
                ) or (
                    step["action_type"] == "wait"
                    and payload.get("wait_for") == "worker_completion"
                )
                if is_packing:
                    step["target_location_id"] = packing["location_id"]
                    payload["packing_dock_location_id"] = packing["location_id"]
                    step["input"] = payload
            self._append_event(
                job_id, None, "job.assignment.persisted", {"assignment": assignment}
            )
            return response

    def get_job_timeline(self, job_id: int) -> list[dict[str, Any]] | None:
        if job_id not in self._jobs:
            return None
        return deepcopy(self._events[job_id])

    def _append_event(self, job_id: int, step_id: int | None, event_type: str, payload: dict[str, Any]) -> None:
        event_id = self._next_event_id
        self._next_event_id += 1
        event = {
            "event_id": event_id,
            "event_uuid": str(uuid.uuid4()),
            "occurred_at": datetime.now(SEOUL),
            "actor_worker_id": None,
            "device_id": None,
            "job_id": job_id,
            "job_step_id": step_id,
            "incident_id": None,
            "severity": "info",
            "category": "operation" if event_type == "job.created" else "rmf",
            "event_type": event_type,
            "message": None,
            "payload": deepcopy(payload),
        }
        self._events[job_id].append(event)
        self._operation_events.append(deepcopy(event))

    def dispatch_step(self, job_step_id: int, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        step = self._steps.get(job_step_id)
        if step is None:
            raise JobStepNotFound
        job_context = self._jobs[step["job_id"]].get("context", {})
        if (
            job_context.get("source") == "public_product_order"
            and not job_context.get("assignment")
        ):
            raise JobStepNotDispatchable
        if (
            step.get("assigned_device_id") is not None
            and request.get("assigned_device_id") is not None
            and request["assigned_device_id"] != step["assigned_device_id"]
        ):
            raise ResourceAssignmentConflict("DISPATCH_ASSIGNED_DEVICE_MISMATCH")
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
        assignment = self._jobs[step["job_id"]].get("context", {}).get("assignment")
        if assignment is not None and assignment["mobile_id"] != robot_id:
            raise ResourceAssignmentConflict("RMF_ASSIGNED_DEVICE_MISMATCH")
        step["rmf_task_id"] = rmf_task_id
        if assignment is None:
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
            step = self._steps[message["job_step_id"]]
            assignment = self._jobs[step["job_id"]].get("context", {}).get(
                "assignment"
            )
            if (
                assignment is not None
                and assignment["mobile_id"] != acceptance["assigned_device_id"]
            ):
                raise ResourceAssignmentConflict("RMF_ASSIGNED_DEVICE_MISMATCH")
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
