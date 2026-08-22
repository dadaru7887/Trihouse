# 이 모듈은 Trihouse FMS Gateway의 FastAPI 진입점으로 동작합니다. HTTP
# 엔드포인트와 웹소켓을 통해 운영 UI·외부 시스템 요청을 받고, 선택적으로
# 로봇 TCP 수집 서버를 함께 기동하여 로봇 관측을 수신합니다. 모든 비즈니스
# 로직과 트랜잭션은 MySQL 기반 Repository에 위임하여 단일 쓰기 프로세스로
# 일관된 상태 변화를 보장합니다.
"""FMS의 유일한 MySQL 쓰기 프로세스를 구성하는 FastAPI 진입점.

이 계층은 HTTP 데이터/오류 계약을 담당하고, 실제 도메인 규칙과 트랜잭션은
Repository에 위임한다.
"""

import asyncio
from contextlib import asynccontextmanager

from datetime import datetime, timezone
import logging
from pathlib import Path as FileSystemPath
import shutil
from typing import Annotated, Literal

from fastapi import (
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)

from .config import get_map_runtime_settings, get_settings, get_tcp_settings
from .database import Database
from .ingestion import RepositoryIngestion
from .operations_ws import OperationEventTailer
from .map_deployment import (
    MapDeploymentCoordinator,
    MapSourceStaging,
    MapWorkflowConflict,
    MapWorkflowError,
)
from .models import (
    RmfTaskUpdate,
    RmfTaskUpdateApplied,
    CommandClaim,
    CommandClaimed,
    DeviceView,
    DispatchRecord,
    InventoryAdjustment,
    InventoryLotView,
    JobCreate,
    JobCreated,
    JobDetail,
    JobAssignmentRequest,
    JobAssignmentView,
    JobCancelRequest,
    JobCancelled,
    AnomalyAcknowledgeRequest,
    AnomalyAcknowledged,
    EmergencyDecisionRecorded,
    EmergencyDecisionRequest,
    ReservationAnomaly,
    ReservationsExpired,
    LoadAttemptRequest,
    MarkerObservationDelivery,
    MarkerObservationReport,
    PersonDetectionDelivery,
    PersonDetectionReport,
    LoadAttemptView,
    PickRecoveryRequest,
    PickRecoveryView,
    RecoveryFactRequest,
    JobTimeline,
    JobView,
    MapProjectDraft,
    MapProjectChanges,
    MapProjectChangesRecorded,
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
    OperationEventView,
    OutboundOrderCreated,
    OutboundOrderRequest,
    RmfDispatchAcceptance,
    RmfDispatchAccepted,
    ExecutorDispatchClaim,
    ExecutorDispatchesClaimed,
    RmfDispatchClaim,
    RmfDispatchesClaimed,
    StepOutcome,
    StepOutcomeView,
    StepDispatch,
    WorkerCompletionRequest,
)
from .runtime_profiles import RuntimeProfileProvider
from .recovery_repository import (
    InMemoryRecoveryRepository,
    MySqlRecoveryRepository,
    RecoveryRepository,
)
from .recovery_dispatch import dispatch_loop
from .recovery_routes import recovery_router
from .repositories import (
    CommandClaimConflict,
    DispatchMessageNotFound,
    FmsRepository,
    IdempotencyConflict,
    InventoryLotNotFound,
    InventoryQuantityConflict,
    JobStepNotDispatchable,
    StepOutcomeConflict,
    JobStepNotFound,
    AnomalyAcknowledgementConflict,
    AnomalyNotFound,
    EmergencyDecisionConflict,
    IncidentNotFound,
    JobCancellationConflict,
    JobNotFound,
    ManualAcknowledgementRequired,
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
    ResourceAssignmentConflict,
    ResourceUnavailable,
    PickRecoveryConflict,
    WorkerCompletionConflict,
)
from .tcp_protocol import (
    PersonDetectionRoutingError,
    RobotLinkRegistry,
    TcpIngestionServer,
    route_person_detection,
)
from control_tower.gateway.camera_registry import load_camera_registry


logger = logging.getLogger(__name__)

# 운영 WebSocket 폴링 간격. 새 이벤트가 없으면 이 간격으로 다시 확인한다.
OPERATIONS_WS_POLL_SECONDS = 0.5


MapNamePath = Annotated[
    str, Path(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,94}$")
]


def _default_repository() -> MySqlFmsRepository:
    """환경 설정을 사용한 운영 MySQL Repository를 만든다."""
    return MySqlFmsRepository(Database(get_settings()))


def create_app(
    repository: FmsRepository | None = None,
    *,
    recovery_repository: RecoveryRepository | None = None,
    map_runtime_root: FileSystemPath | None = None,
    map_source_token_ttl_seconds: float | None = None,
    map_source_max_bytes: int | None = None,
    runtime_profile_provider: RuntimeProfileProvider | None = None,
) -> FastAPI:
    """HTTP API와 선택적인 로봇 TCP 수집 서버를 하나의 수명주기로 묶는다.

    테스트에서 Repository를 주입하면 테스트 앱이 TCP 포트를 열지 않는다.
    """
    owns_runtime = repository is None
    repo = repository or _default_repository()
    recovery_repo = recovery_repository or (
        MySqlRecoveryRepository(Database(get_settings()))
        if owns_runtime else InMemoryRecoveryRepository()
    )
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
        """운영 앱 시작/종료와 TCP 서버 시작/종료를 정확히 대응시킨다."""
        tcp_server = None
        recovery_dispatch_task = None
        source_staging.reconcile_startup(repo)
        deployments.reconcile_startup()
        tcp_settings = get_tcp_settings()
        if owns_runtime and tcp_settings.enabled:
            tcp_server = TcpIngestionServer(
                host=tcp_settings.host,
                port=tcp_settings.port,
                max_line_bytes=tcp_settings.max_line_bytes,
                registered_robot_ids=repo.list_registered_robot_ids,
                on_message=RepositoryIngestion(repo, recovery_repo),
            )
            await tcp_server.start()
            # 관제가 로봇에게 먼저 말을 거는 통로. 사람 관측이 이 장부를 쓴다.
            _app.state.robot_links = tcp_server.links
            recovery_dispatch_task = asyncio.create_task(
                dispatch_loop(recovery_repo, tcp_server.links),
                name="recovery-command-dispatch",
            )
        try:
            yield
        finally:
            if recovery_dispatch_task is not None:
                recovery_dispatch_task.cancel()
                try:
                    await recovery_dispatch_task
                except asyncio.CancelledError:
                    pass
            if tcp_server is not None:
                await tcp_server.stop()

    app = FastAPI(
        title="Trihouse FMS Gateway", version="0.1.0", lifespan=lifespan
    )
    app.state.map_source_staging = source_staging
    app.state.map_deployments = deployments
    # TCP 서버가 없는 구성(테스트, read-only 인스턴스)에서도 라우트가 뜨도록
    # 빈 장부를 먼저 둔다. lifespan 이 실제 서버의 것으로 바꾼다.
    app.state.robot_links = RobotLinkRegistry()
    app.include_router(recovery_router(recovery_repo))

    @app.post(
        "/internal/v1/vision/person-detections",
        response_model=PersonDetectionDelivery,
    )
    async def receive_person_detection(
        observation: PersonDetectionReport, request: Request
    ) -> PersonDetectionDelivery:
        """5080 추론이 올린 사람 관측을 해당 로봇에 밀어 넣는다.

        `docs/architecture/system_overview.md` 의 금지 연결에 `VLM/RL → Safety
        Supervisor 우회` 가 있다. 5080 은 로봇에 직접 꽂히지 않고 여기를 거친다.

        요청은 `robot_id` 를 싣지 않는다 — `config/cameras.yaml` 의 `attached_to`
        가 이미 답이고, 둘을 함께 받으면 어긋날 수 있다. 그 어긋남은 "엉뚱한
        로봇이 감속한다" 로 나타나 현장에서 되짚기가 매우 어렵다.

        실패를 조용히 삼키지 않고 이유를 나눠서 답한다. 카메라 ID 오타와 로봇
        미접속은 현장에서 고치는 방법이 전혀 다르다.
        """
        try:
            robot_id = route_person_detection(observation.camera_id, load_camera_registry())
        except PersonDetectionRoutingError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        payload = observation.model_dump(exclude_none=True)
        payload["type"] = "person_detection"
        delivered = await request.app.state.robot_links.push(robot_id, payload)
        if not delivered:
            raise HTTPException(
                status_code=409, detail=f"{robot_id} is not connected"
            )
        return PersonDetectionDelivery(robot_id=robot_id, delivered=True)

    @app.post(
        "/internal/v1/vision/marker-observations",
        response_model=MarkerObservationDelivery,
    )
    async def receive_marker_observation(
        observation: MarkerObservationReport, request: Request
    ) -> MarkerObservationDelivery:
        """검증된 camera-frame ArUco 관측을 해당 Pinky TCP 링크로 전달한다.

        4060은 영상 인식까지만 담당한다. 카메라 ID에서 로봇을 결정하고 onboard
        TF 변환 전의 좌표를 그대로 보낸다. 관제가 ROS나 모터 명령을 우회하지
        못하도록 이 endpoint는 관측 외의 제어 필드를 받지 않는다.
        """
        try:
            robot_id = route_person_detection(
                observation.camera_id, load_camera_registry()
            )
        except PersonDetectionRoutingError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        payload = observation.model_dump(exclude_none=True)
        payload["type"] = "marker_observation"
        delivered = await request.app.state.robot_links.push(robot_id, payload)
        if not delivered:
            raise HTTPException(
                status_code=409, detail=f"{robot_id} is not connected"
            )
        return MarkerObservationDelivery(robot_id=robot_id, delivered=True)

    @app.get("/health")
    def health() -> dict[str, str]:
        """외부 의존성과 무관한 프로세스 생존(liveness)을 반환한다."""
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> dict[str, str]:
        """DB 연결까지 가능한지 확인하는 준비 상태(readiness)를 반환한다."""
        try:
            if not repo.ping():
                raise RuntimeError("database ping failed")
        except Exception as error:
            raise HTTPException(status_code=503, detail="database unavailable") from error
        return {"status": "ready", "database": "ok"}

    @app.get("/api/v1/devices", response_model=list[DeviceView])
    def devices():
        return repo.list_devices()

    @app.get("/internal/v1/recovery/navigation-context/{device_id}")
    def recovery_navigation_context(device_id: str):
        context = repo.get_recovery_navigation_context(device_id)
        if context is None:
            raise HTTPException(
                status_code=409,
                detail="device has no active map-frame recovery context",
            )
        return context

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
        """멱등 키 아래 재고를 조정하고 도메인 충돌을 404/409로 번역한다."""
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

    # /api/v1/orders 주소로 POST 요청 -> create_outbound_order 함수 실행
    @app.post(
        "/api/v1/orders", response_model=OutboundOrderCreated, status_code=201
    )
    def create_outbound_order(
        order: OutboundOrderRequest,
        idempotency_key: str = Header(min_length=1, max_length=160),
    ):
        """EN: Create one product-only order, with or without worker identity.

        KO: 작업자 식별 여부와 무관하게 상품 주문 하나를 생성한다.
        """
        try:
            return repo.create_outbound_order(order.model_dump(), idempotency_key)
        except OutboundOrderInsufficientStock as error:     # 재고 부족
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "INSUFFICIENT_STOCK",
                    "shortages": list(error.shortages),
                },
            ) from error
        except OutboundOrderProductNotFound as error:       # 상품 없음/중복/모호함
            raise HTTPException(
                status_code=422,
                detail={"code": error.code, "product": error.product_reference},
            ) from error
        except OutboundOrderActiveMapUnavailable as error:  # 활성 지도나 도크 없음
            raise HTTPException(
                status_code=409,
                detail={"code": "ACTIVE_MAP_UNAVAILABLE", "message": str(error)},
            ) from error
        except IdempotencyConflict as error:                # 동일한 멱등성 키로 다른 요청 데이터가 유입
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
    def get_map_project(map_name: MapNamePath):
        project = repo.get_map_project(map_name)
        if project is None:
            raise HTTPException(status_code=404, detail="map project not found")
        return project

    @app.put(
        "/internal/v1/map-projects/{map_name}", response_model=MapProjectDraft
    )
    def save_map_project(
        map_name: MapNamePath,
        project: MapProjectSave,
        if_match: str | None = Header(default=None),
    ):
        """If-Match revision을 사용해 오래된 지도 편집의 덮어쓰기를 막는다."""
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
    def delete_map_project(map_name: MapNamePath):
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
    def validate_map_project(map_name: MapNamePath):
        try:
            return repo.validate_map_project(map_name)
        except MapProjectNotFound as error:
            raise HTTPException(status_code=404, detail="map project not found") from error

    @app.post(
        "/internal/v1/map-projects/{map_name}/publish",
        response_model=PublishedMap,
    )
    def publish_map_project(map_name: MapNamePath, publication: MapProjectPublish):
        """검증된 지도 초안을 콘텐츠 해시 기반 불변 revision으로 발행한다."""
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
    def get_published_map(map_name: MapNamePath):
        publication = repo.get_published_map(map_name)
        if publication is None:
            raise HTTPException(status_code=404, detail="published map not found")
        return publication

    @app.post(
        "/internal/v1/map-projects/{map_name}/changes",
        response_model=MapProjectChangesRecorded,
        status_code=201,
    )
    def record_map_project_changes(map_name: MapNamePath, request: MapProjectChanges):
        try:
            events = repo.record_map_project_changes(
                map_name, [change.model_dump() for change in request.changes]
            )
        except MapProjectNotFound as error:
            raise HTTPException(status_code=404, detail="map project not found") from error
        return {"map_name": map_name, "events": events}

    @app.get("/api/v1/operation-events", response_model=list[OperationEventView])
    def operation_events(
        from_at: datetime | None = Query(default=None, alias="from"),
        to_at: datetime | None = Query(default=None, alias="to"),
        before_at: datetime | None = Query(default=None),
        before_event_id: int | None = Query(default=None, ge=1),
        limit: int = Query(default=100, ge=1, le=500),
    ):
        if (before_at is None) != (before_event_id is None):
            raise HTTPException(
                status_code=422,
                detail="before_at and before_event_id must be provided together",
            )
        return repo.list_operation_events(
            from_at, to_at, limit, before_at, before_event_id
        )

    @app.websocket("/api/v1/operations/ws")
    async def operations_ws(websocket: WebSocket) -> None:
        """운영 화면에 새 operation event만 순서대로 밀어 준다.

        구독 시점 이전의 과거 이벤트는 다시 보내지 않는다. UI는 필요한 과거
        구간을 `GET /api/v1/operation-events`로 따로 가져간다.
        """
        await websocket.accept()
        tailer = OperationEventTailer(repo)
        try:
            await asyncio.to_thread(tailer.start_from_latest)
            while True:
                events = await asyncio.to_thread(tailer.poll)
                for event in events:
                    await websocket.send_json(event)
                await asyncio.sleep(OPERATIONS_WS_POLL_SECONDS)
        except WebSocketDisconnect:
            return
        except Exception:
            logger.exception("operations WebSocket closed on an unexpected error")
            await websocket.close(code=1011)

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
        """현재 실행 가능한 Job Step을 RMF/설비용 outbox 메시지로 만든다."""
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
        except ResourceAssignmentConflict as error:
            raise HTTPException(
                status_code=409, detail={"code": str(error)}
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
        """RMF worker가 처리할 대기 dispatch를 제한 개수만큼 선점한다."""
        return {"dispatches": repo.claim_rmf_dispatches(claim.worker_id, claim.limit)}

    @app.post(
        "/internal/v1/executor/dispatches/claim",
        response_model=ExecutorDispatchesClaimed,
    )
    def claim_executor_dispatches(claim: ExecutorDispatchClaim):
        """OMX·FMS 실행기가 처리할 대기 dispatch를 제한 개수만큼 선점한다."""
        return {
            "dispatches": repo.claim_executor_dispatches(
                claim.worker_id, tuple(claim.channels), claim.limit
            )
        }

    @app.post(
        "/internal/v1/job-steps/{job_step_id}/outcome",
        response_model=StepOutcomeView,
    )
    def record_step_outcome(
        job_step_id: int,
        outcome: StepOutcome,
        idempotency_key: str = Header(min_length=1, max_length=160),
    ):
        """비이동 실행기의 종료 결과를 Step에 반영한다."""
        try:
            return repo.record_executor_outcome(
                job_step_id, outcome.model_dump(mode="json"), idempotency_key
            )
        except JobStepNotFound as error:
            raise HTTPException(status_code=404, detail="job step not found") from error
        except ResourceAssignmentConflict as error:
            raise HTTPException(
                status_code=409, detail={"code": str(error)}
            ) from error
        except StepOutcomeConflict as error:
            raise HTTPException(
                status_code=409,
                detail={"code": str(error) or "STEP_OUTCOME_CONFLICT"},
            ) from error
        except IdempotencyConflict as error:
            raise HTTPException(
                status_code=409,
                detail="idempotency key was already used for another request",
            ) from error

    @app.post(
        "/internal/v1/rmf/dispatches/{message_id}/acceptance",
        response_model=RmfDispatchAccepted,
    )
    def accept_rmf_dispatch(message_id: str, acceptance: RmfDispatchAcceptance):
        """RMF의 수락 결과와 task/robot 배정을 원래 Step에 연결한다."""
        try:
            return repo.record_rmf_dispatch_acceptance(
                message_id, acceptance.model_dump()
            )
        except DispatchMessageNotFound as error:
            raise HTTPException(status_code=404, detail="RMF dispatch not found") from error
        except ResourceAssignmentConflict as error:
            raise HTTPException(
                status_code=409, detail={"code": str(error)}
            ) from error
        except (JobStepNotDispatchable, IdempotencyConflict) as error:
            raise HTTPException(status_code=409, detail="RMF dispatch state conflict") from error

    @app.post(
        "/internal/v1/rmf/tasks/{rmf_task_id}/updates",
        response_model=RmfTaskUpdateApplied,
    )
    def apply_rmf_task_update(rmf_task_id: str, update: RmfTaskUpdate):
        """입찰이 끝난 뒤 RMF 가 관측한 배정을 원래 Step 에 반영한다.

        이 경로가 없으면 dispatch 는 `sent` 에 머물다 재시도를 소진해
        dead_letter 가 되고, 주문이 로봇을 움직이지 못한다.
        """
        try:
            return repo.apply_rmf_task_update(rmf_task_id, update.model_dump())
        except JobStepNotFound as error:
            raise HTTPException(
                status_code=404, detail="RMF task is not known to this gateway"
            ) from error
        except ResourceAssignmentConflict as error:
            raise HTTPException(
                status_code=409, detail={"code": str(error)}
            ) from error

    @app.post(
        "/internal/v1/rmf/tasks/{rmf_task_id}/commands/claim",
        response_model=CommandClaimed,
    )
    def claim_command(rmf_task_id: str, claim: CommandClaim):
        """로봇 명령 실행에 사용할 서버 발급 task_context를 반환한다."""
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

    @app.post(
        "/api/v1/jobs/{job_id}/worker-completion", response_model=JobDetail
    )
    def complete_worker_packing(
        job_id: int,
        completion: WorkerCompletionRequest,
        idempotency_key: str = Header(min_length=1, max_length=160),
    ):
        try:
            return repo.complete_worker_packing(
                job_id, completion.model_dump(), idempotency_key
            )
        except JobNotFound as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except ManualAcknowledgementRequired as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "MANUAL_ACKNOWLEDGEMENT_REQUIRED",
                    "item_ids": list(error.item_ids),
                },
            ) from error
        except WorkerCompletionConflict as error:
            raise HTTPException(
                status_code=409, detail={"code": error.code}
            ) from error
        except IdempotencyConflict as error:
            raise HTTPException(
                status_code=409, detail={"code": "IDEMPOTENCY_CONFLICT"}
            ) from error

    @app.post(
        "/internal/v1/jobs/{job_id}/assignment",
        response_model=JobAssignmentView,
    )
    def persist_job_assignment(job_id: int, assignment: JobAssignmentRequest):
        try:
            return repo.assign_job_resources(job_id, assignment.model_dump())
        except JobNotFound as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except ResourceAssignmentConflict as error:
            raise HTTPException(
                status_code=409,
                detail={"code": str(error) or "ASSIGNMENT_CONFLICT"},
            ) from error
        except ResourceUnavailable as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "RESOURCE_UNAVAILABLE", "message": str(error)},
            ) from error

    @app.post("/internal/v1/jobs/{job_id}/cancel", response_model=JobCancelled)
    def cancel_job(
        job_id: int,
        cancellation: JobCancelRequest,
        idempotency_key: str = Header(min_length=1, max_length=160),
    ):
        """Job 을 닫고 그것이 쥐고 있던 로봇·팔·Dock 을 한 트랜잭션으로 돌려준다.

        RMF 에 제출되기 전에 멈춘 job 은 `rmf_task_repository` 의 해제 경로를 타지
        못해 자원을 영원히 쥔다. 그때 원장을 손으로 고치는 대신 이 경로를 쓴다.
        """
        try:
            return repo.cancel_job(job_id, cancellation.model_dump(), idempotency_key)
        except JobNotFound as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except JobCancellationConflict as error:
            raise HTTPException(
                status_code=409, detail={"code": error.code}
            ) from error
        except IdempotencyConflict as error:
            raise HTTPException(
                status_code=409, detail={"code": "IDEMPOTENCY_CONFLICT"}
            ) from error

    @app.post(
        "/internal/v1/reservations/expire", response_model=ReservationsExpired
    )
    def expire_reservations():
        """만료된 예약을 돌려받고 위험한 만료만 사람에게 올린다.

        `job_runner` 가 매 주기 이것을 먼저 호출한 뒤 배정을 계산한다. 그러면 다음
        주기에 자원이 실제로 비어 보인다.
        """
        return repo.expire_reservations()

    @app.get(
        "/api/v1/operations/anomalies", response_model=list[ReservationAnomaly]
    )
    def list_anomalies(state: Literal["open"] = "open"):
        """아직 아무도 확인하지 않은 이상. 지금은 열린 것만 돌려준다."""
        return repo.list_open_anomalies()

    @app.post(
        "/api/v1/operations/anomalies/{correlation_uuid}/acknowledge",
        response_model=AnomalyAcknowledged,
    )
    def acknowledge_anomaly(
        correlation_uuid: str, acknowledgement: AnomalyAcknowledgeRequest
    ):
        """사람이 그 이상을 봤다고 원장에 적는다.

        이 경로가 없으면 이상은 열리기만 하고 아무도 닫지 못한다.
        """
        try:
            return repo.acknowledge_anomaly(
                correlation_uuid, acknowledgement.model_dump()
            )
        except AnomalyNotFound as error:
            raise HTTPException(status_code=404, detail="anomaly not found") from error
        except AnomalyAcknowledgementConflict as error:
            raise HTTPException(
                status_code=409, detail={"code": error.code}
            ) from error

    @app.post(
        "/api/v1/incidents/{incident_id}/decision",
        response_model=EmergencyDecisionRecorded,
    )
    def decide_incident_emergency(
        incident_id: int,
        decision: EmergencyDecisionRequest,
        idempotency_key: str = Header(min_length=1, max_length=160),
    ):
        """운영자의 비상 판단을 원장에 적는다.

        이 라우트가 없던 동안 관제 화면의 비상 버튼은 404 로 조용히 사라졌다.
        안전 판단은 눌렸다는 사실 자체가 감사 대상이므로 실패가 조용하면 안 된다.
        """
        try:
            return repo.decide_incident_emergency(
                incident_id, decision.model_dump(), idempotency_key
            )
        except IncidentNotFound as error:
            raise HTTPException(
                status_code=404, detail="incident not found"
            ) from error
        except IdempotencyConflict as error:
            raise HTTPException(
                status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED"}
            ) from error
        except EmergencyDecisionConflict as error:
            raise HTTPException(
                status_code=409, detail={"code": error.code}
            ) from error

    @app.post(
        "/internal/v1/job-steps/{job_step_id}/load-attempts",
        response_model=LoadAttemptView,
    )
    def record_load_attempt(
        job_step_id: int,
        attempt: LoadAttemptRequest,
        idempotency_key: str = Header(min_length=1, max_length=160),
    ):
        try:
            return repo.record_load_attempt(
                job_step_id, attempt.model_dump(), idempotency_key
            )
        except JobStepNotFound as error:
            raise HTTPException(status_code=404, detail="load step not found") from error
        except (ResourceAssignmentConflict, PickRecoveryConflict) as error:
            raise HTTPException(status_code=409, detail={"code": str(error)}) from error
        except IdempotencyConflict as error:
            raise HTTPException(
                status_code=409, detail={"code": "IDEMPOTENCY_CONFLICT"}
            ) from error

    @app.post(
        "/internal/v1/job-steps/{job_step_id}/pick-recovery",
        response_model=PickRecoveryView,
    )
    def record_pick_recovery_choice(
        job_step_id: int,
        recovery: PickRecoveryRequest,
        idempotency_key: str = Header(min_length=1, max_length=160),
    ):
        try:
            return repo.record_pick_recovery(
                job_step_id, recovery.model_dump(), idempotency_key
            )
        except JobStepNotFound as error:
            raise HTTPException(status_code=404, detail="load step not found") from error
        except PickRecoveryConflict as error:
            raise HTTPException(status_code=409, detail={"code": str(error)}) from error
        except IdempotencyConflict as error:
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_CONFLICT"}) from error

    @app.post(
        "/internal/v1/job-steps/{job_step_id}/recovery-facts",
        response_model=PickRecoveryView,
    )
    def record_recovery_fact(
        job_step_id: int,
        recovery: RecoveryFactRequest,
        idempotency_key: str = Header(min_length=1, max_length=160),
    ):
        try:
            return repo.record_pick_recovery(
                job_step_id, recovery.model_dump(), idempotency_key
            )
        except JobStepNotFound as error:
            raise HTTPException(status_code=404, detail="load step not found") from error
        except PickRecoveryConflict as error:
            raise HTTPException(status_code=409, detail={"code": str(error)}) from error
        except IdempotencyConflict as error:
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_CONFLICT"}) from error

    @app.get("/api/v1/jobs/{job_id}/timeline", response_model=JobTimeline)
    def job_timeline(job_id: int):
        events = repo.get_job_timeline(job_id)
        if events is None:
            raise HTTPException(status_code=404, detail="job not found")
        return {"job_id": job_id, "events": events}

    return app
