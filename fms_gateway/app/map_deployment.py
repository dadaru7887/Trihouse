"""Secure source staging and stage/validate/activate map deployment workflow."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePath
import re
import secrets
import shutil
import time
from typing import Any, Iterable
import uuid

import yaml

from .physical_features import (
    PhysicalFeatureImport,
    PhysicalFeatureImportError,
    PhysicalFeatureImporter,
)
from .runtime_profiles import RuntimeProfileProvider


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


class MapWorkflowError(ValueError):
    """Stable public validation error with a concrete machine-readable code."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


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
        self.runtime_profiles = runtime_profiles

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
            source_manifest.append(
                {
                    "source_type": source_type,
                    "source_uuid": source_uuid,
                    "file_name": source["file_name"],
                    "mime_type": source["mime_type"],
                    "sha256": source["sha256"],
                    "byte_size": source["byte_size"],
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
        draft = self.repository.get_public_map_draft(staged.map_name)
        if draft is None:
            errors.add("MAP_DRAFT_NOT_FOUND")
        elif draft["draft_revision"] != staged.draft_revision:
            errors.add("DRAFT_REVISION_CHANGED")
        elif hashlib.sha256(_canonical_json(draft)).hexdigest() != manifest.get(
            "snapshot_sha256"
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

        by_type = {
            value["source_type"]: value
            for value in manifest.get("source_manifest", [])
            if isinstance(value, dict) and "source_type" in value
        }
        for required in ("slam_yaml", "slam_image", "physical_features_import"):
            if required not in by_type:
                errors.add(f"SOURCE_{required.upper()}_MISSING")
        for source_type, source_manifest in by_type.items():
            source = self.repository.get_map_project_source(
                staged.map_name, source_manifest.get("source_uuid", "")
            )
            if source is None:
                errors.add("SOURCE_REFERENCE_INVALID")
                continue
            if (
                source.get("sha256") != source_manifest.get("sha256")
                or source.get("byte_size") != source_manifest.get("byte_size")
            ):
                errors.add("SOURCE_HASH_MISMATCH")
                continue
            if source_type == "slam_yaml":
                try:
                    parsed = yaml.safe_load(source["content_bytes"])
                    if not isinstance(parsed, dict):
                        raise ValueError
                except (ValueError, yaml.YAMLError):
                    errors.add("SLAM_YAML_INVALID")
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
                        physical_waypoints != imported_waypoints
                        or physical_features != imported_features
                    ):
                        errors.add("PHYSICAL_FEATURE_RECORD_SET_MISMATCH")
                except PhysicalFeatureImportError:
                    errors.add("PHYSICAL_FEATURES_INVALID")
        for artifact in manifest.get("artifacts", {}).values():
            if not isinstance(artifact, dict):
                errors.add("RUNTIME_ARTIFACT_INVALID")
                continue
            content = artifact.get("content")
            if not isinstance(content, str) or hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest() != artifact.get("sha256"):
                errors.add("RUNTIME_ARTIFACT_HASH_MISMATCH")
        return tuple(sorted(errors))

    def activate(self, staged: StagedDeployment, published_by: str) -> dict[str, Any]:
        errors = self.validate(staged)
        if errors:
            raise MapWorkflowError("DEPLOYMENT_VALIDATION_FAILED", ", ".join(errors))
        manifest = self._manifest(staged)
        artifacts = manifest["artifacts"]
        hash_identity = {
            "building_sha256": artifacts["building_yaml"]["sha256"],
            "nav_graph_sha256": artifacts["nav_graph_yaml"]["sha256"],
            "world_sha256": artifacts["world_sdf"]["sha256"],
        }
        revision_hash = hashlib.sha256(
            json.dumps(
                hash_identity, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        publication = {
            "map_revision": f"{staged.map_name}:{revision_hash}",
            **hash_identity,
            "building_yaml_content": artifacts["building_yaml"]["content"],
            "nav_graph_yaml_content": artifacts["nav_graph_yaml"]["content"],
            "world_content": artifacts["world_sdf"]["content"],
            "published_by": published_by,
            "manifest": {
                **manifest,
                "map_revision": f"{staged.map_name}:{revision_hash}",
            },
        }
        published = self.repository.publish_map_project(staged.map_name, publication)
        self._write_active_manifest(manifest, published)
        shutil.rmtree(staged.staging_dir, ignore_errors=True)
        return published

    def _write_active_manifest(
        self, manifest: dict[str, Any], published: dict[str, Any]
    ) -> None:
        map_name = str(published["map_name"])
        map_revision = str(published["map_revision"])
        revision_suffix = map_revision.removeprefix(f"{map_name}:")
        revision_dir = self.active_root / map_name / revision_suffix
        revision_dir.mkdir(parents=True, exist_ok=True)
        active_manifest = revision_dir / "manifest.json"
        temporary_manifest = revision_dir / ".manifest.tmp"
        temporary_manifest.write_bytes(_canonical_json(manifest))
        os.replace(temporary_manifest, active_manifest)
        pointer = self.active_root / f"{map_name}.json"
        temporary_pointer = (
            self.active_root / f".{map_name}.{manifest['deployment_uuid']}.tmp"
        )
        temporary_pointer.write_bytes(
            _canonical_json(
                {
                    "deployment_uuid": manifest["deployment_uuid"],
                    "map_name": map_name,
                    "map_revision": map_revision,
                    "manifest_path": str(active_manifest),
                }
            )
        )
        os.replace(temporary_pointer, pointer)

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
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                deployment_uuid = directory.name
                shutil.rmtree(directory, ignore_errors=True)
                reconciled.append(deployment_uuid)
                continue
            active = self.repository.get_published_map(map_name)
            if (
                active is not None
                and active.get("manifest", {}).get("deployment_uuid")
                == deployment_uuid
            ):
                self._write_active_manifest(manifest, active)
            shutil.rmtree(directory, ignore_errors=True)
            reconciled.append(deployment_uuid)
        return tuple(reconciled)
