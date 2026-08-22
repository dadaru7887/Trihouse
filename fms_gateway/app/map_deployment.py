"""Secure source staging and stage/validate/activate map deployment workflow."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path, PurePath
import re
import secrets
import shutil
import struct
import threading
import time
from typing import Any, Iterable
import uuid
import zlib

import yaml

from .physical_features import (
    PhysicalFeatureImport,
    PhysicalFeatureImportError,
    PhysicalFeatureImporter,
)
from .runtime_profiles import RuntimeProfileProvider
from .repositories import (
    MapDraftRevisionConflict,
    MapProjectValidationError,
    MapRevisionContentConflict,
)


SOURCE_MIME_TYPES = {
    "slam_yaml": frozenset(
        {"application/x-yaml", "application/yaml", "text/yaml"}
    ),
    "slam_image": frozenset(
        {"image/png", "image/x-portable-graymap", "application/octet-stream"}
    ),
    "floor_plan": frozenset({"image/png", "image/jpeg", "application/pdf"}),
    "physical_features_import": frozenset(
        {"application/x-ndjson", "application/json", "text/plain"}
    ),
}
UPLOAD_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
RUNTIME_ARTIFACT_KEYS = frozenset(
    {"building_yaml", "nav_graph_yaml", "world_sdf"}
)
_PUBLICATION_LOCKS_GUARD = threading.Lock()
_PUBLICATION_LOCKS: dict[tuple[str, str], threading.RLock] = {}


class MapWorkflowError(ValueError):
    """Stable public validation error with a concrete machine-readable code."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


class MapWorkflowConflict(MapWorkflowError):
    """Stable conflict for a well-formed request that lost a concurrent race."""


@dataclass(frozen=True, slots=True)
class StagedMapSource:
    upload_token: str
    map_name: str
    source_uuid: str
    source_type: str
    file_name: str
    mime_type: str
    sha256: str
    byte_size: int
    expires_at: float
    content_path: Path
    metadata: dict[str, Any] | None

    def repository_source(self) -> dict[str, Any]:
        return {
            "source_uuid": self.source_uuid,
            "source_type": self.source_type,
            "file_name": self.file_name,
            "mime_type": self.mime_type,
            "content_bytes": self.content_path.read_bytes(),
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class ClaimedMapSource:
    source: StagedMapSource
    claimed_dir: Path


@dataclass(frozen=True, slots=True)
class StagedDeployment:
    deployment_uuid: str
    map_name: str
    draft_revision: int
    staging_dir: Path
    manifest_path: Path


def physical_import_to_public_records(
    imported: PhysicalFeatureImport,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Expose every imported pose once without deriving or substituting coordinates."""
    waypoints = [
        {
            "code": waypoint.source_id,
            "display_name": waypoint.display_name,
            "rmf_waypoint_name": waypoint.rmf_waypoint_name,
            "location_code": waypoint.location_code,
            "operational_role": waypoint.operational_role,
            "parent_location_code": waypoint.parent_location_code,
            "temperature_zone": waypoint.temperature_zone,
            "x": waypoint.pose.x,
            "y": waypoint.pose.y,
            "yaw": waypoint.pose.yaw,
            "origin": "physical_features_import",
        }
        for waypoint in imported.waypoints
    ]
    features: list[dict[str, Any]] = [
        {
            "type": "bottleneck",
            "code": feature.source_id,
            "display_name": feature.display_name,
            "feature_code": feature.feature_code,
            "mutex_group": feature.mutex_group,
            "x": feature.pose.x,
            "y": feature.pose.y,
            "radius_m": feature.radius_m,
            "source_diameter_m": feature.source_diameter_m,
            "origin": "physical_features_import",
        }
        for feature in imported.bottlenecks
    ]
    features.extend(
        {
            "type": "fiducial_binding",
            "code": binding.source_id,
            "marker_id": binding.marker_id,
            "dictionary": binding.dictionary,
            "target_location_code": binding.target_location_code,
            "x": binding.recognition_pose.x,
            "y": binding.recognition_pose.y,
            "yaw": binding.recognition_pose.yaw,
            "pixel_size": binding.pixel_size,
            "origin": "physical_features_import",
        }
        for binding in imported.fiducials
    )
    return waypoints, features


def _physical_records_equal(
    left: object,
    right: object,
    *,
    numeric_abs_tol: float = 1e-12,
) -> bool:
    """Compare persisted JSON records without rejecting harmless float roundoff."""
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _physical_records_equal(
                left[key], right[key], numeric_abs_tol=numeric_abs_tol
            )
            for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _physical_records_equal(a, b, numeric_abs_tol=numeric_abs_tol)
            for a, b in zip(left, right, strict=True)
        )
    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    ):
        return math.isclose(
            float(left),
            float(right),
            rel_tol=0.0,
            abs_tol=numeric_abs_tol,
        )
    return left == right


class MapSourceStaging:
    """Filesystem-only source uploads with opaque, expiring, project-bound tokens."""

    def __init__(
        self,
        runtime_root: Path,
        *,
        token_ttl_seconds: float = 900,
        max_bytes: int = 20 * 1024 * 1024,
    ):
        if token_ttl_seconds <= 0:
            raise ValueError("token_ttl_seconds must be positive")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.runtime_root = runtime_root.resolve()
        self.pending_root = self.runtime_root / "source-staging" / "pending"
        self.claimed_root = self.runtime_root / "source-staging" / "claimed"
        self.token_ttl_seconds = token_ttl_seconds
        self.max_bytes = max_bytes

    @staticmethod
    def _validate_filename(file_name: str) -> None:
        if (
            not file_name
            or len(file_name) > 255
            or "\x00" in file_name
            or file_name in {".", ".."}
            or PurePath(file_name).name != file_name
            or "/" in file_name
            or "\\" in file_name
        ):
            raise MapWorkflowError(
                "SOURCE_FILENAME_INVALID", "source filename must be one plain basename"
            )

    def stage(
        self,
        map_name: str,
        source_type: str,
        file_name: str,
        mime_type: str,
        content: bytes,
    ) -> StagedMapSource:
        if source_type not in SOURCE_MIME_TYPES:
            raise MapWorkflowError(
                "SOURCE_TYPE_UNSUPPORTED", "unsupported map source type"
            )
        self._validate_filename(file_name)
        normalized_mime = mime_type.split(";", 1)[0].strip().lower()
        if normalized_mime not in SOURCE_MIME_TYPES[source_type]:
            raise MapWorkflowError(
                "SOURCE_MIME_INVALID", "MIME type is not allowed for source type"
            )
        if not content:
            raise MapWorkflowError("SOURCE_EMPTY", "source file must not be empty")
        if len(content) > self.max_bytes:
            raise MapWorkflowError(
                "SOURCE_SIZE_EXCEEDED", "source file exceeds configured byte limit"
            )

        public_metadata = None
        if source_type == "physical_features_import":
            try:
                imported = PhysicalFeatureImporter().parse(content)
            except PhysicalFeatureImportError as error:
                raise MapWorkflowError(
                    "PHYSICAL_FEATURES_INVALID", str(error)
                ) from error
            waypoints, features = physical_import_to_public_records(imported)
            public_metadata = {
                "physical_map_name": imported.map_name,
                "waypoints": waypoints,
                "features": features,
            }

        token = secrets.token_urlsafe(32)
        source_uuid = str(uuid.uuid4())
        expires_at = time.time() + self.token_ttl_seconds
        directory = self.pending_root / token
        directory.mkdir(parents=True, exist_ok=False)
        content_path = directory / "content.bin"
        content_path.write_bytes(content)
        metadata = {
            "upload_token": token,
            "map_name": map_name,
            "source_uuid": source_uuid,
            "source_type": source_type,
            "file_name": file_name,
            "mime_type": normalized_mime,
            "sha256": hashlib.sha256(content).hexdigest(),
            "byte_size": len(content),
            "expires_at": expires_at,
            "metadata": public_metadata,
        }
        (directory / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        return self._source_from_dir(directory)

    @staticmethod
    def _source_from_dir(directory: Path) -> StagedMapSource:
        try:
            metadata = json.loads(
                (directory / "metadata.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise MapWorkflowError(
                "STAGED_SOURCE_TOKEN_INVALID", "staged source metadata is invalid"
            ) from error
        content_path = directory / "content.bin"
        try:
            actual_size = content_path.stat().st_size
            actual_hash = hashlib.sha256(content_path.read_bytes()).hexdigest()
        except OSError as error:
            raise MapWorkflowError(
                "STAGED_SOURCE_TOKEN_INVALID", "staged source content is missing"
            ) from error
        if (
            actual_size != metadata.get("byte_size")
            or actual_hash != metadata.get("sha256")
        ):
            raise MapWorkflowError(
                "STAGED_SOURCE_TOKEN_INVALID", "staged source content hash is invalid"
            )
        try:
            return StagedMapSource(
                upload_token=str(metadata["upload_token"]),
                map_name=str(metadata["map_name"]),
                source_uuid=str(uuid.UUID(str(metadata["source_uuid"]))),
                source_type=str(metadata["source_type"]),
                file_name=str(metadata["file_name"]),
                mime_type=str(metadata["mime_type"]),
                sha256=str(metadata["sha256"]),
                byte_size=int(metadata["byte_size"]),
                expires_at=float(metadata["expires_at"]),
                content_path=content_path,
                metadata=metadata.get("metadata"),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise MapWorkflowError(
                "STAGED_SOURCE_TOKEN_INVALID", "staged source metadata is incomplete"
            ) from error

    def claim_many(
        self, map_name: str, tokens_by_type: dict[str, str]
    ) -> tuple[ClaimedMapSource, ...]:
        prepared: list[StagedMapSource] = []
        for requested_type, token in tokens_by_type.items():
            if not isinstance(token, str) or not UPLOAD_TOKEN_PATTERN.fullmatch(token):
                raise MapWorkflowError(
                    "STAGED_SOURCE_TOKEN_INVALID", "upload token is invalid"
                )
            pending = self.pending_root / token
            if not pending.is_dir():
                raise MapWorkflowError(
                    "STAGED_SOURCE_TOKEN_INVALID", "upload token is absent or consumed"
                )
            source = self._source_from_dir(pending)
            if source.map_name != map_name:
                raise MapWorkflowError(
                    "STAGED_SOURCE_PROJECT_MISMATCH",
                    "upload token belongs to another map project",
                )
            if source.source_type != requested_type:
                raise MapWorkflowError(
                    "STAGED_SOURCE_TYPE_MISMATCH",
                    "upload token source type does not match its draft slot",
                )
            if time.time() >= source.expires_at:
                shutil.rmtree(pending, ignore_errors=True)
                raise MapWorkflowError(
                    "STAGED_SOURCE_TOKEN_EXPIRED", "upload token has expired"
                )
            prepared.append(source)

        claimed: list[ClaimedMapSource] = []
        try:
            self.claimed_root.mkdir(parents=True, exist_ok=True)
            for source in prepared:
                pending = self.pending_root / source.upload_token
                claimed_dir = self.claimed_root / source.upload_token
                pending.rename(claimed_dir)
                claimed_source = self._source_from_dir(claimed_dir)
                claimed.append(ClaimedMapSource(claimed_source, claimed_dir))
        except FileNotFoundError as error:
            self.restore_claims(claimed)
            raise MapWorkflowConflict(
                "STAGED_SOURCE_TOKEN_CONSUMED",
                "upload token was consumed by another save",
            ) from error
        except Exception:
            self.restore_claims(claimed)
            raise
        return tuple(claimed)

    def restore_claims(self, claims: Iterable[ClaimedMapSource]) -> None:
        self.pending_root.mkdir(parents=True, exist_ok=True)
        for claim in reversed(tuple(claims)):
            if claim.claimed_dir.exists():
                claim.claimed_dir.rename(
                    self.pending_root / claim.source.upload_token
                )

    @staticmethod
    def discard_claims(claims: Iterable[ClaimedMapSource]) -> None:
        for claim in claims:
            shutil.rmtree(claim.claimed_dir, ignore_errors=True)

    def reconcile_startup(self, repository: Any) -> tuple[str, ...]:
        reconciled: list[str] = []
        now = time.time()
        for directory in sorted(self.pending_root.glob("*")):
            if not directory.is_dir():
                continue
            try:
                source = self._source_from_dir(directory)
            except MapWorkflowError:
                shutil.rmtree(directory, ignore_errors=True)
                reconciled.append(directory.name)
                continue
            if now >= source.expires_at:
                shutil.rmtree(directory, ignore_errors=True)
                reconciled.append(source.upload_token)
        for directory in sorted(self.claimed_root.glob("*")):
            if not directory.is_dir():
                continue
            try:
                source = self._source_from_dir(directory)
            except MapWorkflowError:
                shutil.rmtree(directory, ignore_errors=True)
                reconciled.append(directory.name)
                continue
            stored = repository.get_map_project_source(
                source.map_name, source.source_uuid
            )
            if stored is not None or now >= source.expires_at:
                shutil.rmtree(directory, ignore_errors=True)
            else:
                self.pending_root.mkdir(parents=True, exist_ok=True)
                directory.rename(self.pending_root / source.upload_token)
            reconciled.append(source.upload_token)
        return tuple(reconciled)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _content_identity(content: object) -> tuple[bytes, str, int] | None:
    if not isinstance(content, (bytes, bytearray)):
        return None
    raw = bytes(content)
    return raw, hashlib.sha256(raw).hexdigest(), len(raw)


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _validate_slam_yaml(content: bytes, image_file_name: str) -> bool:
    try:
        parsed = yaml.safe_load(content)
    except (UnicodeDecodeError, yaml.YAMLError):
        return False
    if not isinstance(parsed, dict) or set(
        ("image", "resolution", "origin", "negate", "occupied_thresh", "free_thresh")
    ) - set(parsed):
        return False
    image = parsed.get("image")
    if (
        not isinstance(image, str)
        or PurePath(image).name != image
        or image != image_file_name
    ):
        return False
    resolution = parsed.get("resolution")
    origin = parsed.get("origin")
    negate = parsed.get("negate")
    occupied = parsed.get("occupied_thresh")
    free = parsed.get("free_thresh")
    return (
        _finite_number(resolution)
        and float(resolution) > 0
        and isinstance(origin, list)
        and len(origin) == 3
        and all(_finite_number(value) for value in origin)
        and isinstance(negate, int)
        and not isinstance(negate, bool)
        and negate in {0, 1}
        and _finite_number(occupied)
        and _finite_number(free)
        and 0.0 <= float(free) < float(occupied) <= 1.0
    )


def _pgm_shape(content: bytes) -> tuple[int, int] | None:
    position = 0

    def token() -> bytes | None:
        nonlocal position
        while position < len(content):
            if content[position] in b" \t\r\n":
                position += 1
                continue
            if content[position] == ord("#"):
                newline = content.find(b"\n", position)
                position = len(content) if newline < 0 else newline + 1
                continue
            break
        start = position
        while position < len(content) and content[position] not in b" \t\r\n#":
            position += 1
        return content[start:position] if position > start else None

    try:
        magic = token()
        width = int(token() or b"")
        height = int(token() or b"")
        maximum = int(token() or b"")
    except ValueError:
        return None
    if magic not in {b"P2", b"P5"} or width <= 0 or height <= 0:
        return None
    if maximum <= 0 or maximum > 65535 or position >= len(content):
        return None
    if magic == b"P2":
        values: list[int] = []
        try:
            while (value := token()) is not None:
                values.append(int(value))
        except ValueError:
            return None
        if len(values) != width * height or any(
            value < 0 or value > maximum for value in values
        ):
            return None
    else:
        if content[position : position + 2] == b"\r\n":
            position += 2
        elif content[position] in b" \t\r\n":
            position += 1
        else:
            return None
        bytes_per_pixel = 1 if maximum < 256 else 2
        if len(content) - position != width * height * bytes_per_pixel:
            return None
    return width, height


def _png_shape(content: bytes) -> tuple[int, int] | None:
    if (
        len(content) < 33
        or content[:8] != b"\x89PNG\r\n\x1a\n"
        or content[12:16] != b"IHDR"
        or struct.unpack(">I", content[8:12])[0] != 13
    ):
        return None
    width, height = struct.unpack(">II", content[16:24])
    bit_depth, color_type, compression, filtering, interlace = content[24:29]
    valid_depths = {
        0: {1, 2, 4, 8, 16},
        2: {8, 16},
        3: {1, 2, 4, 8},
        4: {8, 16},
        6: {8, 16},
    }
    if (
        width <= 0
        or height <= 0
        or bit_depth not in valid_depths.get(color_type, set())
        or compression != 0
        or filtering != 0
        or interlace != 0
    ):
        return None
    position = 8
    chunks: list[tuple[bytes, bytes]] = []
    try:
        while position + 12 <= len(content):
            length = struct.unpack(">I", content[position : position + 4])[0]
            chunk_type = content[position + 4 : position + 8]
            end = position + 12 + length
            if end > len(content):
                return None
            data = content[position + 8 : position + 8 + length]
            expected_crc = struct.unpack(">I", content[position + 8 + length : end])[0]
            if zlib.crc32(chunk_type + data) & 0xFFFFFFFF != expected_crc:
                return None
            chunks.append((chunk_type, data))
            position = end
            if chunk_type == b"IEND":
                break
    except struct.error:
        return None
    if (
        position != len(content)
        or not chunks
        or chunks[0][0] != b"IHDR"
        or chunks[-1] != (b"IEND", b"")
        or not any(chunk_type == b"IDAT" for chunk_type, _ in chunks)
        or (color_type == 3 and not any(chunk_type == b"PLTE" for chunk_type, _ in chunks))
    ):
        return None
    compressed = b"".join(data for chunk_type, data in chunks if chunk_type == b"IDAT")
    try:
        pixels = zlib.decompress(compressed)
    except zlib.error:
        return None
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    row_bytes = (width * channels * bit_depth + 7) // 8
    if len(pixels) != height * (row_bytes + 1):
        return None
    for row in range(height):
        if pixels[row * (row_bytes + 1)] > 4:
            return None
    return width, height


def _slam_image_shape(content: bytes, file_name: str) -> tuple[int, int] | None:
    suffix = PurePath(file_name).suffix.lower()
    if suffix == ".pgm":
        return _pgm_shape(content)
    if suffix == ".png":
        return _png_shape(content)
    return None


def _revision_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    artifacts = manifest["artifacts"]
    return {
        "snapshot_sha256": manifest["snapshot_sha256"],
        "runtime_profile_hash": manifest["runtime_profile_hash"],
        "source_manifest_sha256": hashlib.sha256(
            _canonical_json(manifest["source_manifest"])
        ).hexdigest(),
        "artifact_sha256": {
            name: artifacts[name]["sha256"] for name in sorted(RUNTIME_ARTIFACT_KEYS)
        },
    }


def _runtime_artifacts(
    map_name: str, public_draft: dict[str, Any]
) -> dict[str, dict[str, str]]:
    vertices = [
        [
            float(waypoint["x"]),
            float(waypoint["y"]),
            {"name": waypoint.get("rmf_waypoint_name") or waypoint["code"]},
        ]
        for waypoint in public_draft.get("waypoints", [])
    ]
    building = yaml.safe_dump(
        {
            "name": map_name,
            "levels": {"L1": {"vertices": vertices, "lanes": []}},
        },
        allow_unicode=True,
        sort_keys=True,
    )
    nav_graph = yaml.safe_dump(
        {
            "building_name": map_name,
            "levels": {"L1": {"vertices": vertices, "lanes": []}},
        },
        allow_unicode=True,
        sort_keys=True,
    )
    world = (
        "<?xml version=\"1.0\"?>\n"
        f"<sdf version=\"1.9\"><world name=\"{map_name}\"/></sdf>\n"
    )
    return {
        name: {
            "content": content,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }
        for name, content in (
            ("building_yaml", building),
            ("nav_graph_yaml", nav_graph),
            ("world_sdf", world),
        )
    }


class MapDeploymentCoordinator:
    """Create immutable staging manifests and activate them only after validation."""

    def __init__(
        self,
        repository: Any,
        runtime_root: Path,
        runtime_profiles: RuntimeProfileProvider,
    ):
        self.repository = repository
        self.runtime_root = runtime_root.resolve()
        self.staging_root = self.runtime_root / "staging"
        self.active_root = self.runtime_root / "active"
        self.lock_root = self.runtime_root / "locks" / "map-publication"
        self.runtime_profiles = runtime_profiles

    @contextmanager
    def _publication_lock(self, map_name: str):
        lock_key = (str(self.runtime_root), map_name)
        with _PUBLICATION_LOCKS_GUARD:
            thread_lock = _PUBLICATION_LOCKS.setdefault(
                lock_key, threading.RLock()
            )
        lock_file_name = (
            hashlib.sha256(map_name.encode("utf-8")).hexdigest() + ".lock"
        )
        with thread_lock:
            self.lock_root.mkdir(parents=True, exist_ok=True)
            lock_path = self.lock_root / lock_file_name
            flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
            lock_fd = os.open(lock_path, flags, 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    def stage(self, map_name: str, draft_revision: int) -> StagedDeployment:
        draft = self.repository.get_public_map_draft(map_name)
        if draft is None:
            raise MapWorkflowError("MAP_DRAFT_NOT_FOUND", "map draft not found")
        if int(draft["draft_revision"]) != int(draft_revision):
            raise MapWorkflowError(
                "DRAFT_REVISION_CHANGED", "draft revision changed before staging"
            )
        deployment_uuid = str(uuid.uuid4())
        staging_dir = self.staging_root / deployment_uuid
        staging_dir.mkdir(parents=True, exist_ok=False)
        artifacts = _runtime_artifacts(map_name, draft)
        source_manifest = []
        for source_type, source_uuid in sorted(draft.get("source_uuids", {}).items()):
            source = self.repository.get_map_project_source(map_name, source_uuid)
            if source is None:
                continue
            identity = _content_identity(source.get("content_bytes"))
            if identity is None:
                continue
            _, actual_hash, actual_size = identity
            source_manifest.append(
                {
                    "source_type": source_type,
                    "source_uuid": source_uuid,
                    "file_name": source["file_name"],
                    "mime_type": source["mime_type"],
                    "sha256": actual_hash,
                    "byte_size": actual_size,
                }
            )
        snapshot_hash = hashlib.sha256(_canonical_json(draft)).hexdigest()
        manifest = {
            "schema_version": 1,
            "deployment_uuid": deployment_uuid,
            "map_name": map_name,
            "draft_revision": draft_revision,
            "draft_snapshot": draft,
            "snapshot_sha256": snapshot_hash,
            "runtime_profile_hash": draft["runtime_profile_hash"],
            "source_manifest": source_manifest,
            "artifacts": artifacts,
            "staged_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest_path = staging_dir / "manifest.json"
        manifest_path.write_bytes(_canonical_json(manifest))
        return StagedDeployment(
            deployment_uuid=deployment_uuid,
            map_name=map_name,
            draft_revision=draft_revision,
            staging_dir=staging_dir,
            manifest_path=manifest_path,
        )

    @staticmethod
    def _manifest(staged: StagedDeployment) -> dict[str, Any]:
        try:
            manifest = json.loads(staged.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise MapWorkflowError(
                "DEPLOYMENT_MANIFEST_INVALID", "deployment manifest is unreadable"
            ) from error
        if (
            manifest.get("deployment_uuid") != staged.deployment_uuid
            or manifest.get("map_name") != staged.map_name
            or manifest.get("draft_revision") != staged.draft_revision
        ):
            raise MapWorkflowError(
                "DEPLOYMENT_MANIFEST_INVALID", "deployment manifest identity changed"
            )
        return manifest

    def validate(self, staged: StagedDeployment) -> tuple[str, ...]:
        errors: set[str] = set()
        try:
            manifest = self._manifest(staged)
        except MapWorkflowError as error:
            return (error.code,)
        snapshot = manifest.get("draft_snapshot")
        if not isinstance(snapshot, dict):
            errors.add("DEPLOYMENT_SNAPSHOT_INVALID")
            snapshot = {}
        else:
            try:
                snapshot_hash = hashlib.sha256(_canonical_json(snapshot)).hexdigest()
            except (TypeError, ValueError):
                snapshot_hash = ""
            if snapshot_hash != manifest.get("snapshot_sha256"):
                errors.add("DEPLOYMENT_SNAPSHOT_HASH_MISMATCH")
            if (
                snapshot.get("map_name") != staged.map_name
                or snapshot.get("draft_revision") != staged.draft_revision
            ):
                errors.add("DEPLOYMENT_SNAPSHOT_IDENTITY_MISMATCH")
            if snapshot.get("runtime_profile_hash") != manifest.get(
                "runtime_profile_hash"
            ):
                errors.add("DEPLOYMENT_PROFILE_BINDING_MISMATCH")

        source_values = manifest.get("source_manifest")
        if not isinstance(source_values, list):
            errors.add("DEPLOYMENT_SOURCE_MANIFEST_INVALID")
            source_values = []
        by_type: dict[str, dict[str, Any]] = {}
        for value in source_values:
            if (
                not isinstance(value, dict)
                or set(value)
                != {
                    "source_type",
                    "source_uuid",
                    "file_name",
                    "mime_type",
                    "sha256",
                    "byte_size",
                }
                or not isinstance(value.get("source_type"), str)
                or value["source_type"] in by_type
            ):
                errors.add("DEPLOYMENT_SOURCE_MANIFEST_INVALID")
                continue
            by_type[value["source_type"]] = value
        bound_source_uuids = {
            source_type: value.get("source_uuid")
            for source_type, value in by_type.items()
        }
        if snapshot.get("source_uuids") != bound_source_uuids:
            errors.add("DEPLOYMENT_SOURCE_MANIFEST_MISMATCH")

        draft = self.repository.get_public_map_draft(staged.map_name)
        if draft is None:
            errors.add("MAP_DRAFT_NOT_FOUND")
        elif draft["draft_revision"] != staged.draft_revision:
            errors.add("DRAFT_REVISION_CHANGED")
        else:
            try:
                current_snapshot_hash = hashlib.sha256(
                    _canonical_json(draft)
                ).hexdigest()
            except (TypeError, ValueError):
                current_snapshot_hash = ""
            if (
                current_snapshot_hash != manifest.get("snapshot_sha256")
                or draft != snapshot
            ):
                errors.add("DRAFT_SNAPSHOT_CHANGED")

        try:
            current_profile = self.runtime_profiles.load()
        except (OSError, TypeError, ValueError, yaml.YAMLError):
            errors.add("RUNTIME_PROFILE_UNAVAILABLE")
            current_profile = None
        if current_profile is not None and manifest.get(
            "runtime_profile_hash"
        ) != current_profile["profile_hash"]:
            errors.add("RUNTIME_PROFILE_HASH_MISMATCH")

        for required in ("slam_yaml", "slam_image", "physical_features_import"):
            if required not in by_type:
                errors.add(f"SOURCE_{required.upper()}_MISSING")
        persisted_by_type: dict[str, dict[str, Any]] = {}
        for source_type, source_manifest in by_type.items():
            source = self.repository.get_map_project_source(
                staged.map_name, source_manifest.get("source_uuid", "")
            )
            if source is None:
                errors.add("SOURCE_REFERENCE_INVALID")
                continue
            persisted_by_type[source_type] = source
            identity = _content_identity(source.get("content_bytes"))
            if (
                identity is None
                or identity[1] != source_manifest.get("sha256")
                or identity[2] != source_manifest.get("byte_size")
                or source.get("source_uuid") != source_manifest.get("source_uuid")
                or source.get("source_type") != source_type
                or source.get("file_name") != source_manifest.get("file_name")
                or source.get("mime_type") != source_manifest.get("mime_type")
            ):
                errors.add("SOURCE_HASH_MISMATCH")
                continue
            if source_type == "physical_features_import":
                try:
                    imported = PhysicalFeatureImporter().parse(source["content_bytes"])
                    imported_waypoints, imported_features = (
                        physical_import_to_public_records(imported)
                    )
                    physical_waypoints = [
                        value
                        for value in manifest["draft_snapshot"].get("waypoints", [])
                        if value.get("origin") == "physical_features_import"
                    ]
                    physical_features = [
                        value
                        for value in manifest["draft_snapshot"].get("features", [])
                        if value.get("origin") == "physical_features_import"
                    ]
                    if (
                        not _physical_records_equal(
                            physical_waypoints, imported_waypoints
                        )
                        or not _physical_records_equal(
                            physical_features, imported_features
                        )
                    ):
                        errors.add("PHYSICAL_FEATURE_RECORD_SET_MISMATCH")
                except PhysicalFeatureImportError:
                    errors.add("PHYSICAL_FEATURES_INVALID")

        slam_image = persisted_by_type.get("slam_image")
        slam_yaml = persisted_by_type.get("slam_yaml")
        if slam_image is not None:
            image_content = _content_identity(slam_image.get("content_bytes"))
            if image_content is None or _slam_image_shape(
                image_content[0], str(slam_image.get("file_name", ""))
            ) is None:
                errors.add("SLAM_IMAGE_INVALID")
        if slam_yaml is not None and slam_image is not None:
            yaml_content = _content_identity(slam_yaml.get("content_bytes"))
            if yaml_content is None or not _validate_slam_yaml(
                yaml_content[0], str(slam_image.get("file_name", ""))
            ):
                errors.add("SLAM_YAML_INVALID")

        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict) or set(artifacts) != RUNTIME_ARTIFACT_KEYS:
            errors.add("RUNTIME_ARTIFACT_SET_INVALID")
            artifacts = artifacts if isinstance(artifacts, dict) else {}
        expected_artifacts = _runtime_artifacts(staged.map_name, snapshot)
        for name in RUNTIME_ARTIFACT_KEYS:
            artifact = artifacts.get(name)
            if not isinstance(artifact, dict) or set(artifact) != {"content", "sha256"}:
                errors.add("RUNTIME_ARTIFACT_INVALID")
                continue
            content = artifact.get("content")
            if not isinstance(content, str) or hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest() != artifact.get("sha256"):
                errors.add("RUNTIME_ARTIFACT_HASH_MISMATCH")
                continue
            if artifact != expected_artifacts[name]:
                errors.add("RUNTIME_ARTIFACT_CONTENT_MISMATCH")
        return tuple(sorted(errors))

    def activate(self, staged: StagedDeployment, published_by: str) -> dict[str, Any]:
        with self._publication_lock(staged.map_name):
            return self._activate_locked(staged, published_by)

    def _activate_locked(
        self, staged: StagedDeployment, published_by: str
    ) -> dict[str, Any]:
        errors = self.validate(staged)
        if errors:
            shutil.rmtree(staged.staging_dir, ignore_errors=True)
            raise MapWorkflowError("DEPLOYMENT_VALIDATION_FAILED", ", ".join(errors))
        manifest = self._manifest(staged)
        artifacts = manifest["artifacts"]
        hash_identity = {
            "building_sha256": artifacts["building_yaml"]["sha256"],
            "nav_graph_sha256": artifacts["nav_graph_yaml"]["sha256"],
            "world_sha256": artifacts["world_sdf"]["sha256"],
        }
        revision_identity = _revision_identity(manifest)
        revision_hash = hashlib.sha256(_canonical_json(revision_identity)).hexdigest()
        map_revision = f"{staged.map_name}:{revision_hash}"
        publication_manifest = {
            **manifest,
            "map_revision": map_revision,
            "revision_identity": revision_identity,
        }
        publication = {
            "map_revision": map_revision,
            **hash_identity,
            "building_yaml_content": artifacts["building_yaml"]["content"],
            "nav_graph_yaml_content": artifacts["nav_graph_yaml"]["content"],
            "world_content": artifacts["world_sdf"]["content"],
            "published_by": published_by,
            "manifest": publication_manifest,
            "expected_draft": {
                "draft_revision": manifest["draft_revision"],
                "draft_snapshot": manifest["draft_snapshot"],
                "snapshot_sha256": manifest["snapshot_sha256"],
                "source_manifest": manifest["source_manifest"],
                "runtime_profile_hash": manifest["runtime_profile_hash"],
            },
        }
        try:
            published = self.repository.publish_map_project(
                staged.map_name, publication
            )
        except (
            MapDraftRevisionConflict,
            MapProjectValidationError,
            MapRevisionContentConflict,
        ):
            shutil.rmtree(staged.staging_dir, ignore_errors=True)
            raise
        current_active = self.repository.get_published_map(staged.map_name)
        active_manifest = self._validated_active_manifest(
            current_active, expected_map_name=staged.map_name
        )
        self._write_active_manifest(active_manifest, current_active)
        shutil.rmtree(staged.staging_dir, ignore_errors=True)
        return published

    @staticmethod
    def _validated_active_manifest(
        published: object,
        *,
        expected_map_name: str,
        expected_deployment_uuid: str | None = None,
    ) -> dict[str, Any]:
        try:
            if not isinstance(published, dict):
                raise TypeError
            map_name = published["map_name"]
            map_revision = published["map_revision"]
            manifest = published["manifest"]
            if (
                map_name != expected_map_name
                or not isinstance(map_revision, str)
                or not isinstance(manifest, dict)
                or published.get("state") != "published"
                or manifest.get("map_name") != map_name
                or manifest.get("map_revision") != map_revision
            ):
                raise ValueError
            deployment_uuid = manifest.get("deployment_uuid")
            if not isinstance(deployment_uuid, str):
                raise ValueError
            uuid.UUID(deployment_uuid)
            if (
                expected_deployment_uuid is not None
                and deployment_uuid != expected_deployment_uuid
            ):
                raise ValueError
            snapshot = manifest["draft_snapshot"]
            if (
                not isinstance(snapshot, dict)
                or hashlib.sha256(_canonical_json(snapshot)).hexdigest()
                != manifest.get("snapshot_sha256")
            ):
                raise ValueError
            artifacts = manifest["artifacts"]
            if (
                not isinstance(artifacts, dict)
                or set(artifacts) != RUNTIME_ARTIFACT_KEYS
            ):
                raise ValueError
            hash_keys = {
                "building_yaml": "building_sha256",
                "nav_graph_yaml": "nav_graph_sha256",
                "world_sdf": "world_sha256",
            }
            for artifact_name, published_hash_key in hash_keys.items():
                artifact = artifacts[artifact_name]
                if (
                    not isinstance(artifact, dict)
                    or set(artifact) != {"content", "sha256"}
                    or not isinstance(artifact.get("content"), str)
                    or hashlib.sha256(
                        artifact["content"].encode("utf-8")
                    ).hexdigest()
                    != artifact.get("sha256")
                    or published.get(published_hash_key) != artifact.get("sha256")
                ):
                    raise ValueError
            revision_identity = _revision_identity(manifest)
            expected_revision = (
                f"{map_name}:"
                + hashlib.sha256(_canonical_json(revision_identity)).hexdigest()
            )
            if (
                manifest.get("revision_identity") != revision_identity
                or map_revision != expected_revision
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise MapWorkflowError(
                "ACTIVE_PUBLICATION_INVALID",
                "repository Active publication failed immutable identity validation",
            ) from None
        return manifest

    def _write_active_manifest(
        self, manifest: dict[str, Any], published: dict[str, Any]
    ) -> None:
        map_name = str(published["map_name"])
        map_revision = str(published["map_revision"])
        revision_suffix = map_revision.removeprefix(f"{map_name}:")
        revision_dir = self.active_root / map_name / revision_suffix
        revision_dir.mkdir(parents=True, exist_ok=True)
        active_manifest = revision_dir / "manifest.json"
        self._atomic_json_write(active_manifest, _canonical_json(manifest))
        pointer = self.active_root / f"{map_name}.json"
        self._atomic_json_write(
            pointer,
            _canonical_json(
                {
                    "deployment_uuid": manifest["deployment_uuid"],
                    "map_name": map_name,
                    "map_revision": map_revision,
                    "manifest_path": str(active_manifest),
                }
            ),
        )

    @staticmethod
    def _atomic_json_write(destination: Path, content: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / (
            f".{destination.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_fd = os.open(destination.parent, flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def reconcile_startup(self) -> tuple[str, ...]:
        reconciled: list[str] = []
        if not self.staging_root.exists():
            return ()
        for directory in sorted(self.staging_root.iterdir()):
            if not directory.is_dir():
                continue
            manifest_path = directory / "manifest.json"
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                deployment_uuid = str(manifest["deployment_uuid"])
                map_name = str(manifest["map_name"])
                if deployment_uuid != directory.name:
                    raise ValueError
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                deployment_uuid = directory.name
                shutil.rmtree(directory, ignore_errors=True)
                reconciled.append(deployment_uuid)
                continue
            with self._publication_lock(map_name):
                try:
                    locked_manifest = json.loads(
                        manifest_path.read_text(encoding="utf-8")
                    )
                    if (
                        locked_manifest.get("deployment_uuid") != deployment_uuid
                        or locked_manifest.get("map_name") != map_name
                    ):
                        raise ValueError
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    shutil.rmtree(directory, ignore_errors=True)
                    reconciled.append(deployment_uuid)
                    continue
                active = self.repository.get_published_map(map_name)
                if (
                    active is not None
                    and isinstance(active.get("manifest"), dict)
                    and active["manifest"].get("deployment_uuid") == deployment_uuid
                ):
                    active_manifest = self._validated_active_manifest(
                        active,
                        expected_map_name=map_name,
                        expected_deployment_uuid=deployment_uuid,
                    )
                    self._write_active_manifest(active_manifest, active)
                shutil.rmtree(directory, ignore_errors=True)
                reconciled.append(deployment_uuid)
        return tuple(reconciled)
