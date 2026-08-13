"""FastAPI entry point for the only MySQL-writing FMS process."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException

from .config import get_settings, get_tcp_settings
from .database import Database
from .ingestion import RepositoryIngestion
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
    PublishedMap,
    RmfDispatchAcceptance,
    RmfDispatchAccepted,
    RmfDispatchClaim,
    RmfDispatchesClaimed,
    StepDispatch,
)
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
    MapProjectValidationError,
    MapRevisionContentConflict,
    MySqlFmsRepository,
    PublishedMapProjectDeleteConflict,
)
from .tcp_protocol import TcpIngestionServer


def _default_repository() -> MySqlFmsRepository:
    return MySqlFmsRepository(Database(get_settings()))


def create_app(repository: FmsRepository | None = None) -> FastAPI:
    owns_runtime = repository is None
    repo = repository or _default_repository()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        tcp_server = None
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
