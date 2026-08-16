"""FastAPI entry point for the only MySQL-writing FMS process."""

from contextlib import asynccontextmanager

from datetime import datetime, timezone
import logging
from pathlib import Path as FileSystemPath
import shutil
from typing import Annotated

from fastapi import FastAPI, File, Form, Header, HTTPException, Path, UploadFile

from .config import get_map_runtime_settings, get_settings, get_tcp_settings
from .database import Database
from .ingestion import RepositoryIngestion
from .map_deployment import (
    MapDeploymentCoordinator,
    MapSourceStaging,
    MapWorkflowConflict,
    MapWorkflowError,
)
from .models import (
    CommandClaim,
    CommandClaimed,
    DeviceView,
    DispatchRecord,
    InventoryAdjustment,
    InventoryLotView,
    JobCreate,
    JobCreated,
    JobDetail,
    JobTimeline,
    JobView,
    MapProjectDraft,
    MapProjectPublish,
    MapProjectSave,
    MapProjectSummary,
    MapProjectValidation,
    MapProjectOpenRequest,
    MapProjectOpenResponse,
    PublicMapDraft,
    PublicMapDraftSave,
    PublicMapPublish,
    PublicMapValidation,
    PublishedMap,
    RuntimeProfileView,
    StagedMapSourceResponse,
    OutboundOrderCreated,
    OutboundOrderRequest,
    RmfDispatchAcceptance,
    RmfDispatchAccepted,
    RmfDispatchClaim,
    RmfDispatchesClaimed,
    StepDispatch,
)
from .runtime_profiles import RuntimeProfileProvider
from .repositories import (
    CommandClaimConflict,
    DispatchMessageNotFound,
    FmsRepository,
    IdempotencyConflict,
    InventoryLotNotFound,
    InventoryQuantityConflict,
    JobStepNotDispatchable,
    JobStepNotFound,
    MapDraftRevisionConflict,
    MapProjectNotFound,
    MapProjectSourceValidationError,
    MapProjectValidationError,
    MapRevisionContentConflict,
    MySqlFmsRepository,
    OutboundOrderActiveMapUnavailable,
    OutboundOrderInsufficientStock,
    OutboundOrderProductNotFound,
    PublishedMapProjectDeleteConflict,
)
from .tcp_protocol import TcpIngestionServer


logger = logging.getLogger(__name__)


MapNamePath = Annotated[
    str, Path(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,94}$")
]


def _default_repository() -> MySqlFmsRepository:
    return MySqlFmsRepository(Database(get_settings()))


def create_app(
    repository: FmsRepository | None = None,
    *,
    map_runtime_root: FileSystemPath | None = None,
    map_source_token_ttl_seconds: float | None = None,
    map_source_max_bytes: int | None = None,
    runtime_profile_provider: RuntimeProfileProvider | None = None,
) -> FastAPI:
    owns_runtime = repository is None
    repo = repository or _default_repository()
    map_settings = get_map_runtime_settings()
    runtime_root = FileSystemPath(
        map_runtime_root or map_settings.runtime_root
    ).resolve()
    profiles = runtime_profile_provider or RuntimeProfileProvider()
    source_staging = MapSourceStaging(
        runtime_root,
        token_ttl_seconds=(
            map_source_token_ttl_seconds
            if map_source_token_ttl_seconds is not None
            else map_settings.source_token_ttl_seconds
        ),
        max_bytes=(
            map_source_max_bytes
            if map_source_max_bytes is not None
            else map_settings.source_max_bytes
        ),
    )
    deployments = MapDeploymentCoordinator(repo, runtime_root, profiles)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        tcp_server = None
        source_staging.reconcile_startup(repo)
        deployments.reconcile_startup()
        tcp_settings = get_tcp_settings()
        if owns_runtime and tcp_settings.enabled:
            tcp_server = TcpIngestionServer(
                host=tcp_settings.host,
                port=tcp_settings.port,
                max_line_bytes=tcp_settings.max_line_bytes,
                registered_robot_ids=repo.list_registered_robot_ids,
                on_message=RepositoryIngestion(repo),
            )
            await tcp_server.start()
        try:
            yield
        finally:
            if tcp_server is not None:
                await tcp_server.stop()

    app = FastAPI(
        title="Trihouse FMS Gateway", version="0.1.0", lifespan=lifespan
    )
    app.state.map_source_staging = source_staging
    app.state.map_deployments = deployments

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> dict[str, str]:
        try:
            if not repo.ping():
                raise RuntimeError("database ping failed")
        except Exception as error:
            raise HTTPException(status_code=503, detail="database unavailable") from error
        return {"status": "ready", "database": "ok"}

    @app.get("/api/v1/devices", response_model=list[DeviceView])
    def devices():
        return repo.list_devices()

    @app.get("/api/v1/inventory/lots", response_model=list[InventoryLotView])
    def inventory():
        return repo.list_inventory()

    @app.post(
        "/api/v1/inventory/lots/{lot_id}/adjust",
        response_model=InventoryLotView,
    )
    def adjust_inventory(
        lot_id: int,
        adjustment: InventoryAdjustment,
        idempotency_key: str = Header(min_length=1, max_length=160),
    ):
        try:
            return repo.adjust_inventory(
                lot_id,
                adjustment.quantity_delta,
                adjustment.recorded_by,
                adjustment.note,
                idempotency_key,
            )
        except InventoryLotNotFound as error:
            raise HTTPException(status_code=404, detail="inventory lot not found") from error
        except InventoryQuantityConflict as error:
            raise HTTPException(
                status_code=409,
                detail="available quantity cannot be below reserved quantity",
            ) from error
        except IdempotencyConflict as error:
            raise HTTPException(
                status_code=409,
                detail="idempotency key was already used for another request",
            ) from error

    @app.get("/api/v1/jobs", response_model=list[JobView])
    def jobs():
        return repo.list_jobs()

    @app.post(
        "/api/v1/orders", response_model=OutboundOrderCreated, status_code=201
    )
    def create_outbound_order(
        order: OutboundOrderRequest,
        idempotency_key: str = Header(min_length=1, max_length=160),
    ):
        """Create one product-only order in the caller's credentialed session."""
        try:
            return repo.create_outbound_order(order.model_dump(), idempotency_key)
        except OutboundOrderInsufficientStock as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "INSUFFICIENT_STOCK",
                    "shortages": list(error.shortages),
                },
            ) from error
        except OutboundOrderProductNotFound as error:
            raise HTTPException(
                status_code=422,
                detail={"code": error.code, "product": error.product_reference},
            ) from error
        except OutboundOrderActiveMapUnavailable as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "ACTIVE_MAP_UNAVAILABLE", "message": str(error)},
            ) from error
        except IdempotencyConflict as error:
            raise HTTPException(
                status_code=409,
                detail="idempotency key was already used for another request",
            ) from error

    @app.get(
        "/api/v1/runtime-profiles/pinky-pro-simulation",
        response_model=RuntimeProfileView,
    )
    def pinky_pro_simulation_runtime_profile():
        return profiles.load()

    @app.get(
        "/api/v1/map-projects", response_model=list[MapProjectSummary]
    )
    def public_list_map_projects():
        return repo.list_map_projects()

    @app.post(
        "/api/v1/map-projects", response_model=MapProjectOpenResponse
    )
    def public_open_map_project(request: MapProjectOpenRequest):
        draft = repo.get_public_map_draft(request.map_name)
        return {
            "draft": draft
            or {
                "map_name": request.map_name,
                "format_version": 1,
                "draft_revision": 0,
                "source_uuids": {},
                "staged_source_tokens": {},
                "waypoints": [],
                "features": [],
                "runtime_profile_hash": profiles.load()["profile_hash"],
            },
            "open_existing": draft is not None,
            "active_revision": repo.active_revision(request.map_name),
        }

    @app.get(
        "/api/v1/map-projects/{map_name}", response_model=PublicMapDraft
    )
    def public_get_map_project(map_name: MapNamePath):
        draft = repo.get_public_map_draft(map_name)
        if draft is None:
            raise HTTPException(status_code=404, detail="map project not found")
        return draft

    @app.post(
        "/api/v1/map-projects/{map_name}/sources/stage",
        response_model=StagedMapSourceResponse,
        status_code=201,
    )
    async def public_stage_map_source(
        map_name: MapNamePath,
        source_type: str = Form(),
        source: UploadFile = File(),
    ):
        try:
            content = await source.read(source_staging.max_bytes + 1)
            staged = source_staging.stage(
                map_name,
                source_type,
                source.filename or "",
                source.content_type or "",
                content,
            )
        except MapWorkflowError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": error.code, "message": error.detail},
            ) from error
        metadata = staged.metadata or {}
        return {
            "upload_token": staged.upload_token,
            "source_type": staged.source_type,
            "sha256": staged.sha256,
            "byte_size": staged.byte_size,
            "expires_at": datetime.fromtimestamp(staged.expires_at, tz=timezone.utc),
            "waypoints": metadata.get("waypoints", []),
            "features": metadata.get("features", []),
        }

    @app.put(
        "/api/v1/map-projects/{map_name}", response_model=PublicMapDraft
    )
    def public_save_map_project(
        map_name: MapNamePath,
        draft: PublicMapDraftSave,
        if_match: str | None = Header(default=None),
    ):
        if if_match is None:
            raise HTTPException(status_code=428, detail="If-Match is required")
        try:
            expected_revision = int(if_match.strip('"'))
        except ValueError as error:
            raise HTTPException(status_code=400, detail="invalid If-Match revision") from error
        if draft.map_name != map_name or draft.draft_revision != expected_revision:
            raise HTTPException(
                status_code=409, detail="map draft revision conflict"
            )
        current_profile_hash = profiles.load()["profile_hash"]
        if draft.runtime_profile_hash != current_profile_hash:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "RUNTIME_PROFILE_HASH_MISMATCH",
                    "message": "runtime profile changed; reopen the map project",
                },
            )
        claims = ()
        try:
            claims = source_staging.claim_many(
                map_name, dict(draft.staged_source_tokens)
            )
            source_uuids = dict(draft.source_uuids)
            for claim in claims:
                source_uuids[claim.source.source_type] = claim.source.source_uuid

            canonical_waypoints = None
            canonical_features = None
            physical_uuid = source_uuids.get("physical_features_import")
            if physical_uuid:
                physical_source = next(
                    (
                        claim.source
                        for claim in claims
                        if claim.source.source_uuid == physical_uuid
                    ),
                    None,
                )
                metadata = (
                    physical_source.metadata
                    if physical_source is not None
                    else (
                        repo.get_map_project_source(map_name, physical_uuid) or {}
                    ).get("metadata")
                )
                if not isinstance(metadata, dict):
                    raise MapWorkflowError(
                        "PHYSICAL_FEATURES_INVALID",
                        "physical source metadata is missing",
                    )
                canonical_waypoints = metadata.get("waypoints")
                canonical_features = metadata.get("features")
                if not isinstance(canonical_waypoints, list) or not isinstance(
                    canonical_features, list
                ):
                    raise MapWorkflowError(
                        "PHYSICAL_FEATURES_INVALID",
                        "physical source metadata is incomplete",
                    )
            requested = draft.model_dump()
            requested["source_uuids"] = source_uuids
            requested["staged_source_tokens"] = {}
            if canonical_waypoints is not None:
                requested["waypoints"] = canonical_waypoints + [
                    value
                    for value in requested["waypoints"]
                    if value.get("origin") == "manual"
                ]
                requested["features"] = canonical_features
            saved = repo.save_public_map_draft(
                map_name,
                requested,
                expected_revision,
                [claim.source.repository_source() for claim in claims],
            )
            source_staging.discard_claims(claims)
            return saved
        except MapWorkflowConflict as error:
            source_staging.restore_claims(claims)
            raise HTTPException(
                status_code=409,
                detail={"code": error.code, "message": error.detail},
            ) from error
        except MapWorkflowError as error:
            source_staging.restore_claims(claims)
            raise HTTPException(
                status_code=422,
                detail={"code": error.code, "message": error.detail},
            ) from error
        except MapDraftRevisionConflict as error:
            source_staging.restore_claims(claims)
            raise HTTPException(
                status_code=409, detail="map draft revision conflict"
            ) from error
        except MapProjectSourceValidationError as error:
            source_staging.restore_claims(claims)
            raise HTTPException(
                status_code=422,
                detail={"code": "SOURCE_REFERENCE_INVALID", "message": str(error)},
            ) from error
        except Exception:
            source_staging.restore_claims(claims)
            raise

    @app.delete("/api/v1/map-projects/{map_name}/draft", status_code=204)
    def public_delete_map_project(map_name: MapNamePath):
        try:
            repo.delete_public_map_draft(map_name)
        except MapProjectNotFound as error:
            raise HTTPException(status_code=404, detail="map project not found") from error
        except PublishedMapProjectDeleteConflict as error:
            raise HTTPException(
                status_code=409, detail="active manifest cannot restore its draft"
            ) from error

    @app.post(
        "/api/v1/map-projects/{map_name}/validate",
        response_model=PublicMapValidation,
    )
    def public_validate_map_project(map_name: MapNamePath):
        draft = repo.get_public_map_draft(map_name)
        if draft is None:
            raise HTTPException(status_code=404, detail="map project not found")
        staged = deployments.stage(map_name, draft["draft_revision"])
        try:
            errors = deployments.validate(staged)
            return {"valid": not errors, "error_codes": list(errors)}
        finally:
            shutil.rmtree(staged.staging_dir, ignore_errors=True)

    @app.post(
        "/api/v1/map-projects/{map_name}/publish", response_model=PublishedMap
    )
    def public_publish_map_project(
        map_name: MapNamePath, publication: PublicMapPublish
    ):
        draft = repo.get_public_map_draft(map_name)
        if draft is None:
            raise HTTPException(status_code=404, detail="map project not found")
        if draft["draft_revision"] != publication.expected_draft_revision:
            raise HTTPException(status_code=409, detail="map draft revision conflict")
        staged = deployments.stage(map_name, publication.expected_draft_revision)
        errors = deployments.validate(staged)
        if errors:
            shutil.rmtree(staged.staging_dir, ignore_errors=True)
            logger.warning(
                "map deployment validation failed map_name=%s draft_revision=%s codes=%s",
                map_name,
                publication.expected_draft_revision,
                ",".join(errors),
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "DEPLOYMENT_VALIDATION_FAILED",
                    "error_codes": list(errors),
                },
            )
        try:
            return deployments.activate(staged, publication.published_by)
        except MapDraftRevisionConflict as error:
            shutil.rmtree(staged.staging_dir, ignore_errors=True)
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "DRAFT_REVISION_CHANGED",
                    "message": "map draft changed after deployment validation",
                },
            ) from error
        except MapRevisionContentConflict as error:
            shutil.rmtree(staged.staging_dir, ignore_errors=True)
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "MAP_REVISION_CONTENT_CONFLICT",
                    "message": "map revision identity conflicts with stored content",
                },
            ) from error
        except MapWorkflowError as error:
            shutil.rmtree(staged.staging_dir, ignore_errors=True)
            raise HTTPException(
                status_code=422,
                detail={"code": error.code, "message": error.detail},
            ) from error
        except MapProjectValidationError as error:
            shutil.rmtree(staged.staging_dir, ignore_errors=True)
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "DEPLOYMENT_VALIDATION_FAILED",
                    "error_codes": list(error.args[0]),
                },
            ) from error

    @app.get(
        "/internal/v1/map-projects", response_model=list[MapProjectSummary]
    )
    def list_map_projects():
        return repo.list_map_projects()

    @app.get(
        "/internal/v1/map-projects/{map_name}", response_model=MapProjectDraft
    )
    def get_map_project(map_name: str):
        project = repo.get_map_project(map_name)
        if project is None:
            raise HTTPException(status_code=404, detail="map project not found")
        return project

    @app.put(
        "/internal/v1/map-projects/{map_name}", response_model=MapProjectDraft
    )
    def save_map_project(
        map_name: str,
        project: MapProjectSave,
        if_match: str | None = Header(default=None),
    ):
        if not map_name.strip() or len(map_name) > 95:
            raise HTTPException(status_code=422, detail="map name must be 1..95 characters")
        expected_revision = None
        if if_match is not None:
            try:
                expected_revision = int(if_match.strip('"'))
            except ValueError as error:
                raise HTTPException(status_code=400, detail="invalid If-Match revision") from error
        try:
            return repo.save_map_project(
                map_name, project.model_dump(), expected_revision
            )
        except MapDraftRevisionConflict as error:
            raise HTTPException(
                status_code=409, detail="map draft revision conflict"
            ) from error

    @app.delete("/internal/v1/map-projects/{map_name}", status_code=204)
    def delete_map_project(map_name: str):
        try:
            repo.delete_map_project(map_name)
        except MapProjectNotFound as error:
            raise HTTPException(status_code=404, detail="map project not found") from error
        except PublishedMapProjectDeleteConflict as error:
            raise HTTPException(
                status_code=409, detail="published map project cannot be deleted"
            ) from error

    @app.post(
        "/internal/v1/map-projects/{map_name}/validate",
        response_model=MapProjectValidation,
    )
    def validate_map_project(map_name: str):
        try:
            return repo.validate_map_project(map_name)
        except MapProjectNotFound as error:
            raise HTTPException(status_code=404, detail="map project not found") from error

    @app.post(
        "/internal/v1/map-projects/{map_name}/publish",
        response_model=PublishedMap,
    )
    def publish_map_project(map_name: str, publication: MapProjectPublish):
        try:
            return repo.publish_map_project(map_name, publication.model_dump())
        except MapProjectNotFound as error:
            raise HTTPException(status_code=404, detail="map project not found") from error
        except MapProjectValidationError as error:
            raise HTTPException(
                status_code=422, detail={"code": "map project invalid", "errors": error.args[0]}
            ) from error
        except MapRevisionContentConflict as error:
            raise HTTPException(
                status_code=409, detail="map revision content conflict"
            ) from error

    @app.get(
        "/internal/v1/maps/{map_name}/published", response_model=PublishedMap
    )
    def get_published_map(map_name: str):
        publication = repo.get_published_map(map_name)
        if publication is None:
            raise HTTPException(status_code=404, detail="published map not found")
        return publication

    @app.post("/internal/v1/jobs", response_model=JobCreated, status_code=201)
    def create_job(job: JobCreate):
        return repo.create_job(job.model_dump())

    @app.post(
        "/internal/v1/job-steps/{job_step_id}/dispatch",
        response_model=DispatchRecord,
    )
    def dispatch_step(
        job_step_id: int,
        dispatch: StepDispatch,
        idempotency_key: str = Header(min_length=1, max_length=160),
    ):
        try:
            return repo.dispatch_step(
                job_step_id, dispatch.model_dump(), idempotency_key
            )
        except JobStepNotFound as error:
            raise HTTPException(status_code=404, detail="job step not found") from error
        except JobStepNotDispatchable as error:
            raise HTTPException(
                status_code=409,
                detail="job step is not the current pending step",
            ) from error
        except IdempotencyConflict as error:
            raise HTTPException(
                status_code=409,
                detail="idempotency key was already used for another request",
            ) from error

    @app.post(
        "/internal/v1/rmf/dispatches/claim",
        response_model=RmfDispatchesClaimed,
    )
    def claim_rmf_dispatches(claim: RmfDispatchClaim):
        return {"dispatches": repo.claim_rmf_dispatches(claim.worker_id, claim.limit)}

    @app.post(
        "/internal/v1/rmf/dispatches/{message_id}/acceptance",
        response_model=RmfDispatchAccepted,
    )
    def accept_rmf_dispatch(message_id: str, acceptance: RmfDispatchAcceptance):
        try:
            return repo.record_rmf_dispatch_acceptance(
                message_id, acceptance.model_dump()
            )
        except DispatchMessageNotFound as error:
            raise HTTPException(status_code=404, detail="RMF dispatch not found") from error
        except (JobStepNotDispatchable, IdempotencyConflict) as error:
            raise HTTPException(status_code=409, detail="RMF dispatch state conflict") from error

    @app.post(
        "/internal/v1/rmf/tasks/{rmf_task_id}/commands/claim",
        response_model=CommandClaimed,
    )
    def claim_command(rmf_task_id: str, claim: CommandClaim):
        try:
            return repo.claim_command(rmf_task_id, claim.model_dump())
        except JobStepNotFound as error:
            raise HTTPException(status_code=404, detail="RMF task is not mapped") from error
        except CommandClaimConflict as error:
            raise HTTPException(
                status_code=409,
                detail="command claim identity conflicts with the RMF assignment",
            ) from error

    @app.get("/api/v1/jobs/{job_id}", response_model=JobDetail)
    def job_detail(job_id: int):
        job = repo.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.get("/api/v1/jobs/{job_id}/timeline", response_model=JobTimeline)
    def job_timeline(job_id: int):
        events = repo.get_job_timeline(job_id)
        if events is None:
            raise HTTPException(status_code=404, detail="job not found")
        return {"job_id": job_id, "events": events}

    return app
