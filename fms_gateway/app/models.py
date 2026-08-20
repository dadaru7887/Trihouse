"""FMS HTTP API의 요청/응답 계약을 정의하는 Pydantic 모델.

Repository는 dict를 반환하지만 FastAPI 경계에서 이 모델들이 타입, 범위,
필수 조합을 검증하고 OpenAPI 스키마를 만든다.
"""

from collections.abc import Mapping
from datetime import date, datetime
import math
from types import MappingProxyType
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


# 운영 현황 조회 DTO ---------------------------------------------------------


class DeviceView(BaseModel):
    """장치 기본 정보와 가장 최근 상태 projection."""
    device_id: str
    device_type: str
    name: str
    control_mode: str
    state: str | None = None
    health: str | None = None
    battery_pct: float | None = None
    observed_at: datetime | None = None
    # 적재 확인에 필요한 관측. 실행기는 이 값을 근거로만 적재 증거를 제출한다 —
    # 자기가 지어내지 않는다.
    cargo_state: int | None = None
    cargo_sensor_confirmed: bool | None = None
    navigation_state: int | None = None
    current_job_step_id: int | None = None


class InventoryLotView(BaseModel):
    """위치·유효기간·가용/예약 수량을 포함한 재고 lot 조회 결과."""
    lot_id: int
    lot_code: str
    product_code: str
    item_name: str | None = None
    temperature_zone: str
    location_code: str | None = None
    expiry_date: date
    available_qty: int
    reserved_qty: int
    state: str


class InventoryAdjustment(BaseModel):
    """감사 주체와 사유를 포함한 재고 증감 요청."""
    quantity_delta: int
    recorded_by: str = Field(min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=512)

    @field_validator("quantity_delta")
    @classmethod
    def quantity_must_change(cls, value: int) -> int:
        """변화가 없는 조정을 감사 이력에 기록하지 않도록 거절한다."""
        if value == 0:
            raise ValueError("quantity_delta must not be zero")
        return value


class OutboundOrderItemRequest(BaseModel):
    """One product reference and requested quantity; never a route choice."""

    model_config = ConfigDict(extra="forbid")

    product_code: str = Field(min_length=1, max_length=160)
    quantity: int = Field(ge=1, le=100000)


class OutboundOrderRequest(BaseModel):
    """Session-originated product-only outbound order."""

    model_config = ConfigDict(extra="forbid")   # 정의되지 않은 필드 거절

    external_reference: str | None = Field(default=None, min_length=1, max_length=128)
    requested_by: str = Field(min_length=1, max_length=64)
    priority: Literal["normal", "high", "critical"] = "normal"
    allow_partial_fulfillment: bool = False
    items: list[OutboundOrderItemRequest] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def product_references_are_unique(self):
        references = [item.product_code.strip().casefold() for item in self.items]
        if len(references) != len(set(references)):
            raise ValueError("product references must be unique")
        return self


class OutboundOrderItemView(BaseModel):
    line_no: int
    product_code: str
    requested_quantity: int
    reserved_quantity: int
    outstanding_quantity: int


class OutboundOrderCreated(BaseModel):
    job_id: int
    job_code: str
    external_reference: str | None = None
    state: str
    requested_quantity: int
    fulfillable_quantity: int
    outstanding_quantity: int
    items: list[OutboundOrderItemView]


class JobView(BaseModel):
    """목록 화면에 필요한 Job 요약."""
    job_id: int
    job_code: str
    operation_type: str
    priority: str
    state: str
    due_at: datetime | None = None
    assigned_mobile_id: str | None = None
    item_count: int
    step_count: int


# Job 생성·실행 DTO ---------------------------------------------------------


ActionType = Literal[
    "navigate",
    "dock",
    "inspect",
    "pick",
    "load",
    "unload",
    "place",
    "verify",
    "handover",
    "wait",
    "recover",
    "return_home",
    "safety_stop",
]
ExecutorType = Literal["mobile", "arm", "fms"]


class JobStepCreate(BaseModel):
    """Job 안에서 순서대로 실행할 하나의 동작 정의."""
    step_no: int = Field(ge=1, le=65535)
    action_type: ActionType
    executor_type: ExecutorType
    target_location_id: int | None = Field(default=None, ge=1)
    input: dict[str, Any] = Field(default_factory=dict)


class JobCreate(BaseModel):
    """출고 Job과 최소 한 개 Step을 함께 만드는 요청."""
    job_code: str = Field(min_length=1, max_length=64)
    operation_type: Literal["outbound"] = "outbound"
    priority: Literal["critical", "high", "normal", "low"] = "normal"
    requested_by: str | None = Field(default=None, max_length=64)
    external_reference: str | None = Field(default=None, max_length=128)
    source_location_id: int | None = Field(default=None, ge=1)
    destination_location_id: int | None = Field(default=None, ge=1)
    due_at: datetime | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    steps: list[JobStepCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def steps_are_strictly_ordered(self):
        """Step 번호가 중복 없이 오름차순인지 보장한다."""
        numbers = [step.step_no for step in self.steps]
        if numbers != sorted(set(numbers)):
            raise ValueError("steps must have unique, strictly increasing step_no values")
        return self


class CreatedJobStep(BaseModel):
    job_step_id: int
    step_no: int
    action_type: ActionType
    executor_type: ExecutorType
    target_location_id: int | None = None
    state: str


class JobCreated(BaseModel):
    job_id: int
    job_code: str
    state: str
    steps: list[CreatedJobStep]


class JobDetail(BaseModel):
    job_id: int
    job_code: str
    operation_type: str
    priority: str
    state: str
    requested_by: str | None = None
    external_reference: str | None = None
    source_location_id: int | None = None
    destination_location_id: int | None = None
    due_at: datetime | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    items: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[dict[str, Any]]


class WorkerCompletionRequest(BaseModel):
    """Packing worker confirmation that authorizes physical stock finalization."""

    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=64)
    completion_note: str | None = Field(default=None, max_length=512)
    acknowledged_manual_item_ids: list[int] = Field(default_factory=list, max_length=100)

    @field_validator("acknowledged_manual_item_ids")
    @classmethod
    def acknowledgements_are_unique_positive_ids(cls, value: list[int]) -> list[int]:
        if any(item_id <= 0 for item_id in value) or len(value) != len(set(value)):
            raise ValueError("manual item acknowledgements must be unique positive IDs")
        return value


class JobAssignmentRequest(BaseModel):
    """Complete Control Tower selection persisted before any dispatch."""

    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    mobile_id: str = Field(min_length=1, max_length=64)
    omx_id: str = Field(min_length=1, max_length=64)
    packing_dock_code: str = Field(min_length=1, max_length=96)
    charger_code: str = Field(min_length=1, max_length=96)


class JobAssignmentView(JobAssignmentRequest):
    job_id: int


class JobCancelRequest(BaseModel):
    """운영자 또는 관제가 job 을 닫고 그 자원을 돌려받겠다는 요청."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=512)
    requested_by: str = Field(min_length=1, max_length=64)


class JobCancelled(BaseModel):
    """무엇이 실제로 닫혔고 어떤 자원이 돌아왔는지."""

    job_id: int
    state: Literal["cancelled"]
    cancelled_step_ids: list[int]
    cancelled_reservation_ids: list[int]
    released_device_ids: list[str]
    # 살아 있는 outbox 메시지를 남기면 worker 가 취소된 step 을 계속 집는다.
    cancelled_message_ids: list[str] = Field(default_factory=list)


class ExpiredReservation(BaseModel):
    """회수된 예약 한 건과, 그때 그 job 이 아직 일하고 있었는지."""

    reservation_id: int
    job_id: int
    device_id: str | None = None
    location_id: int | None = None
    job_active: bool


class ReservationsExpired(BaseModel):
    expired: list[ExpiredReservation]


class ReservationAnomaly(BaseModel):
    """자원은 풀렸는데 로봇이 아직 거기 있을 수 있는 상태 — 사람이 봐야 한다."""

    correlation_uuid: str
    job_id: int | None = None
    device_id: str | None = None
    occurred_at: datetime
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AnomalyAcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=64)
    note: str = Field(default="", max_length=512)


class EmergencyDecisionRequest(BaseModel):
    """운영자가 비상 상황을 보고 내린 판단.

    `reason` 은 화면이 보여 준 사건 종류를 그대로 싣는다 — 나중에 왜 그렇게
    판단했는지 되짚을 때 필요한 것은 결정 자체가 아니라 그때 본 것이다.
    """

    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=64)
    decision: Literal["RAISE_ALARM", "CONTINUE_WORK"]
    reason: str = Field(default="", max_length=512)


class EmergencyDecisionRecorded(BaseModel):
    incident_id: int
    incident_code: str
    state: str
    decision: str
    decided_by: str
    reason: str


class AnomalyAcknowledged(BaseModel):
    correlation_uuid: str
    job_id: int | None = None
    acknowledged_by: str
    note: str


LoadResult = Literal[
    "LOAD_CONFIRMED", "DROP_DETECTED", "LOAD_UNCERTAIN", "GRASP_RETAINED"
]


class LoadAttemptRequest(BaseModel):
    """Complete fixture-observed load evidence; never an OMX motion request."""

    model_config = ConfigDict(extra="forbid")

    attempt_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    job_id: int = Field(ge=1)
    item_id: int = Field(ge=1)
    handover_group_id: str = Field(min_length=1, max_length=128)
    assignment_revision: int = Field(ge=1)
    pinky_id: str = Field(min_length=1, max_length=64)
    omx_id: str = Field(min_length=1, max_length=64)
    result: LoadResult
    criteria: dict[str, Any] = Field(min_length=1)
    observations: dict[str, Any] = Field(min_length=1)
    metrics: dict[str, Any] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    policy_name: str = Field(min_length=1, max_length=128)
    policy_version: str = Field(min_length=1, max_length=128)
    model_name: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)


class LoadAttemptView(LoadAttemptRequest):
    departure_allowed: bool


class PickRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: int = Field(ge=1)
    item_id: int = Field(ge=1)
    operator_id: str = Field(min_length=1, max_length=64)
    choice: Literal["재시도", "포장대에서 처리"]


class RecoveryFactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: int = Field(ge=1)
    item_id: int = Field(ge=1)
    operator_id: str = Field(min_length=1, max_length=64)
    fact: Literal["object-recovered", "area-clear"]


class PickRecoveryView(BaseModel):
    job_id: int
    item_id: int
    retry_no: int = 0
    drop_hold: bool
    manual_required: bool = False
    reobserve_qr_aruco: bool = False
    reset_act_episode: bool = False


class StepDispatch(BaseModel):
    actor: str = Field(min_length=1, max_length=64)
    occurred_at: datetime | None = None
    assigned_device_id: str | None = Field(default=None, max_length=64)
    retry: bool = False


class DispatchRecord(BaseModel):
    """Job Step을 실행자에게 전달하기 위한 outbox 메시지."""
    message_id: str
    idempotency_key: str
    job_id: int
    job_step_id: int
    channel: str
    message_type: str
    state: str
    payload: dict[str, Any]


class TimelineEvent(BaseModel):
    event_id: int
    event_uuid: str
    occurred_at: datetime
    job_step_id: int | None = None
    severity: str
    category: str
    event_type: str
    message: str | None = None
    payload: dict[str, Any] | None = None


class JobTimeline(BaseModel):
    """Job의 감사 가능한 상태 변화 이벤트 모음."""
    job_id: int
    events: list[TimelineEvent]


# RMF와 로봇 명령 인계 DTO --------------------------------------------------


class RmfTaskUpdate(BaseModel):
    """RMF 가 관측한 task 진행 상태. 입찰이 끝난 뒤의 배정이 여기 실려 온다."""

    model_config = ConfigDict(extra="forbid")

    fleet_name: str = Field(default="", max_length=64)
    robot_name: str = Field(default="", max_length=64)
    rmf_status: str = Field(min_length=1, max_length=64)
    step_state: str = Field(min_length=1, max_length=24)
    observed_at_ms: int = Field(ge=0)
    detail: str = Field(default="", max_length=512)


class RmfTaskUpdateApplied(BaseModel):
    rmf_task_id: str
    job_step_id: int
    assigned_device_id: str | None = None
    settled: bool


class CommandClaim(BaseModel):
    """RMF task를 실제 로봇 실행 identity에 연결하는 요청."""
    robot_id: str = Field(min_length=1, max_length=64)
    execution_id: str = Field(min_length=1, max_length=160)
    map_revision: str = Field(min_length=1, max_length=160)


class TaskContext(BaseModel):
    """늦거나 잘못된 로봇 이벤트를 식별하는 서버 발급 실행 문맥."""
    active: bool
    job_id: int
    job_step_id: int
    assignment_revision: int
    rmf_task_id: str
    command_id: str
    map_revision: str
    command_source: Literal["rmf"]


class CommandClaimed(BaseModel):
    task_context: TaskContext
    # 이 이동 뒤에 같은 장소에서 인계 단계가 이어지는가. 로봇이 도착을
    # 알릴지 여부가 여기서 갈린다.
    handover_expected: bool = False


class RmfDispatchClaim(BaseModel):
    worker_id: str = Field(min_length=1, max_length=64)
    limit: int = Field(default=1, ge=1, le=100)


class RmfDispatchesClaimed(BaseModel):
    dispatches: list[DispatchRecord]


class ExecutorDispatchClaim(BaseModel):
    """Claim request from the OMX/FMS executor worker."""

    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=64)
    channels: list[Literal["omx", "pinky"]] = Field(min_length=1)
    limit: int = Field(default=1, ge=1, le=100)


class ExecutorDispatchRecord(DispatchRecord):
    """Outbox message plus the step context the executor needs to act."""

    action_type: str
    executor_type: str
    assigned_device_id: str | None = None
    assignment_revision: int = 0
    assignment: dict[str, Any] = Field(default_factory=dict)


class ExecutorDispatchesClaimed(BaseModel):
    dispatches: list[ExecutorDispatchRecord]


class StepOutcome(BaseModel):
    """Terminal report from a non-mobile executor for one job step."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["succeeded", "failed"]
    assignment_revision: int = Field(ge=0)
    method_code: str = Field(min_length=1, max_length=96)
    actor_device_id: str | None = Field(default=None, max_length=64)
    reason_code: str | None = Field(default=None, max_length=96)
    # `db/schema_mysql.sql` 의 chk_attempts_failure_domain 과 같은 집합이다.
    failure_domain: Literal[
        "none", "robot", "perception", "navigation", "manipulation",
        "safety", "integration", "operator", "unknown",
    ] = "none"
    detail: str | None = Field(default=None, max_length=1024)
    started_at: datetime | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def failure_needs_a_domain(self):
        if self.outcome == "failed" and self.failure_domain == "none":
            raise ValueError("a failed outcome must name its failure domain")
        return self


class StepOutcomeView(BaseModel):
    job_step_id: int
    job_id: int
    state: str
    attempt_uuid: str
    attempt_no: int


class RmfDispatchAcceptance(BaseModel):
    """RMF가 dispatch를 수락했는지와 실제 task/robot 매핑을 전달한다."""
    accepted: bool
    rmf_task_id: str | None = Field(default=None, max_length=128)
    assigned_device_id: str | None = Field(default=None, max_length=64)
    detail: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def accepted_dispatch_requires_mapping(self):
        """수락된 요청은 RMF task와 담당 robot을 반드시 확정하게 한다."""
        if self.accepted and not (self.rmf_task_id and self.assigned_device_id):
            raise ValueError("accepted dispatch requires rmf_task_id and assigned_device_id")
        return self


class RmfDispatchAccepted(BaseModel):
    message_id: str
    job_step_id: int
    state: str
    rmf_task_id: str | None = None


# 지도 편집·검증·발행 DTO ---------------------------------------------------


MapProjectSourceType = Literal[
    "slam_yaml",
    "slam_image",
    "floor_plan",
    "physical_features_import",
]


class MapProjectOpenRequest(BaseModel):
    map_name: str = Field(
        pattern=r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,94}$"
    )


class PublicMapWaypoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=160)
    rmf_waypoint_name: str | None = Field(default=None, max_length=128)
    location_code: str | None = Field(default=None, max_length=96)
    operational_role: str | None = Field(default=None, max_length=40)
    parent_location_code: str | None = Field(default=None, max_length=96)
    temperature_zone: Literal["ambient", "chilled", "frozen"] | None = None
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)
    yaw: float = Field(allow_inf_nan=False)
    origin: Literal["physical_features_import", "manual"]


class PublicMapFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["bottleneck", "fiducial_binding"]
    code: str = Field(min_length=1, max_length=128)
    display_name: str | None = Field(default=None, max_length=160)
    feature_code: str | None = Field(default=None, max_length=128)
    mutex_group: str | None = Field(default=None, max_length=64)
    marker_id: int | None = Field(default=None, ge=0)
    dictionary: str | None = Field(default=None, max_length=64)
    target_location_code: str | None = Field(default=None, max_length=96)
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)
    yaw: float | None = Field(default=None, allow_inf_nan=False)
    radius_m: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    source_diameter_m: float | None = Field(
        default=None, gt=0, allow_inf_nan=False
    )
    pixel_size: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    origin: Literal["physical_features_import"]

    @model_validator(mode="after")
    def fields_match_feature_type(self):
        if self.type == "bottleneck" and not (
            self.feature_code
            and self.mutex_group
            and self.radius_m is not None
            and self.source_diameter_m is not None
        ):
            raise ValueError("bottleneck fields are incomplete")
        if self.type == "fiducial_binding" and not (
            self.marker_id is not None
            and self.dictionary
            and self.target_location_code
            and self.yaw is not None
            and self.pixel_size is not None
        ):
            raise ValueError("fiducial binding fields are incomplete")
        return self


class PublicMapDraftSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_name: str = Field(
        pattern=r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,94}$"
    )
    format_version: int = Field(ge=1)
    draft_revision: int = Field(ge=0)
    source_uuids: dict[MapProjectSourceType, str] = Field(default_factory=dict)
    staged_source_tokens: dict[MapProjectSourceType, str] = Field(
        default_factory=dict
    )
    waypoints: list[PublicMapWaypoint] = Field(default_factory=list)
    features: list[PublicMapFeature] = Field(default_factory=list)
    runtime_profile_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class PublicMapDraft(BaseModel):
    map_name: str
    format_version: int
    draft_revision: int
    source_uuids: dict[str, str]
    staged_source_tokens: dict[str, str] = Field(default_factory=dict)
    waypoints: list[dict[str, Any]]
    features: list[dict[str, Any]]
    runtime_profile_hash: str


class MapProjectOpenResponse(BaseModel):
    draft: PublicMapDraft
    open_existing: bool
    active_revision: str | None


class StagedMapSourceResponse(BaseModel):
    upload_token: str
    source_type: MapProjectSourceType
    sha256: str
    byte_size: int
    expires_at: datetime
    waypoints: list[dict[str, Any]] = Field(default_factory=list)
    features: list[dict[str, Any]] = Field(default_factory=list)


class PublicMapValidation(BaseModel):
    valid: bool
    error_codes: list[str]


class PublicMapPublish(BaseModel):
    expected_draft_revision: int = Field(ge=1)
    published_by: str = Field(min_length=1, max_length=64)


class RuntimeProfileView(BaseModel):
    profile_name: Literal["pinky_pro simulation profile"]
    profile_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_files: list[str]
    controller: dict[str, Any]
    planner: dict[str, Any]
    local_costmap: dict[str, Any]
    global_costmap: dict[str, Any]
    robot: dict[str, Any]
    max_speeds: dict[str, Any]
    goal_tolerances: dict[str, Any]
    progress_tolerances: dict[str, Any]
    wheel_parameters: dict[str, Any]


def _freeze_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("metadata object keys must be strings")
        return MappingProxyType(
            {key: _freeze_json_value(nested) for key, nested in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json_value(nested) for nested in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("metadata must contain finite JSON values")


def _thaw_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json_value(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json_value(nested) for nested in value]
    return value


class MapProjectSourceView(BaseModel):
    """Project-scoped immutable source metadata; source bytes stay server-side."""

    model_config = ConfigDict(frozen=True)

    source_uuid: str = Field(
        pattern=(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        )
    )
    source_type: MapProjectSourceType
    file_name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=128)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0)
    metadata: Mapping[str, Any] | None = None
    created_at: datetime

    @model_validator(mode="after")
    def freeze_metadata_recursively(self):
        if self.metadata is not None:
            object.__setattr__(self, "metadata", _freeze_json_value(self.metadata))
        return self

    @field_serializer("metadata")
    def serialize_metadata(self, value: Mapping[str, Any] | None):
        return _thaw_json_value(value) if value is not None else None


class MapProjectFile(BaseModel):
    """지도 프로젝트에 함께 보관하는 생성/설정 파일."""
    file_name: str = Field(min_length=1, max_length=255)
    kind: str = Field(min_length=1, max_length=32)
    description: str = Field(default="", max_length=512)
    executable: bool = False
    content: str


class MapProjectFleet(BaseModel):
    fleet_name: str = Field(min_length=1, max_length=96)
    settings: dict[str, Any] = Field(default_factory=dict)


class MapProjectRobot(BaseModel):
    robot_id: str = Field(min_length=1, max_length=64)
    seq: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=96)
    kind: Literal["mobile", "workcell"]
    data_source: Literal["mock", "gazebo", "real"]
    gz_name: str = Field(min_length=1, max_length=64)
    zones: list[str] = Field(default_factory=list)
    charger_waypoint_name: str | None = Field(default=None, max_length=128)
    spawn_x: float | None = None
    spawn_y: float | None = None
    spawn_heading: float = 0.0


class MapProjectSave(BaseModel):
    """편집 가능한 지도 초안 전체를 원자적으로 저장하는 요청."""
    format_version: int = Field(ge=1)
    payload: dict[str, Any]
    building_yaml: str | None = None
    building_yaml_name: str | None = Field(default=None, max_length=255)
    files: list[MapProjectFile] = Field(default_factory=list)
    fleet: MapProjectFleet | None = None
    robots: list[MapProjectRobot] = Field(default_factory=list)


class MapProjectSummary(BaseModel):
    map_name: str = Field(min_length=1, max_length=95)
    drawing_name: str | None = None
    format_version: int
    waypoint_count: int
    lane_count: int
    draft_revision: int
    has_building_yaml: bool
    updated_at: datetime


class MapProjectDraft(MapProjectSummary):
    payload: dict[str, Any]
    building_yaml: str | None = None
    building_yaml_name: str | None = None
    files: list[dict[str, Any]] = Field(default_factory=list)
    fleet: dict[str, Any] | None = None
    robots: list[dict[str, Any]] = Field(default_factory=list)


class MapProjectValidation(BaseModel):
    valid: bool
    errors: list[str]


class MapProjectPublish(BaseModel):
    """콘텐츠 해시로 검증할 세 RMF/Gazebo artifact 발행 요청."""
    map_revision: str = Field(min_length=1, max_length=160)
    building_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    nav_graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    world_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    building_yaml_content: str = Field(min_length=1)
    nav_graph_yaml_content: str = Field(min_length=1)
    world_content: str = Field(min_length=1)
    published_by: str = Field(min_length=1, max_length=64)
    manifest: dict[str, Any] = Field(default_factory=dict)


class PublishedMap(BaseModel):
    """실행 환경이 재사용할 수 있는 불변 지도 revision 메타데이터."""
    map_revision: str
    map_name: str
    draft_revision: int
    state: Literal["published", "retired"]
    building_sha256: str
    nav_graph_sha256: str
    world_sha256: str
    manifest: dict[str, Any]
    published_by: str
    published_at: datetime


# 전역 운영 이벤트 DTO ------------------------------------------------------


class MapProjectChange(BaseModel):
    category: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=256)
    summary: str = Field(min_length=1, max_length=512)


class MapProjectChanges(BaseModel):
    changes: list[MapProjectChange] = Field(min_length=1, max_length=100)


class OperationEventView(BaseModel):
    event_id: int
    event_uuid: str
    occurred_at: datetime
    actor_worker_id: str | None = None
    device_id: str | None = None
    job_id: int | None = None
    job_step_id: int | None = None
    incident_id: int | None = None
    severity: str
    category: str
    event_type: str
    message: str | None = None
    payload: dict[str, Any] | None = None


class MapProjectChangesRecorded(BaseModel):
    map_name: str
    events: list[OperationEventView]


class PersonDetectionReport(BaseModel):
    """5080 추론이 올리는 사람 관측.

    `robot_id` 를 받지 않는다. `config/cameras.yaml` 의 `attached_to` 가 수신
    로봇을 정하고, 같은 사실을 두 곳에서 받으면 어긋날 수 있다. `extra="forbid"`
    가 실수로 실어 보낸 `robot_id` 를 조용히 무시하지 않고 거절한다.

    `pose` 는 캘리브레이션이 끝난 카메라만 싣는다. 없으면 안전 gate 가 거리
    대신 "보이면 감속" 으로 동작한다 — 지어낸 좌표를 싣지 않는다.
    """

    model_config = ConfigDict(extra="forbid")

    camera_id: str = Field(min_length=1, max_length=64)
    confidence: float = Field(gt=0.0, le=1.0)
    ttl_ms: int | None = Field(default=None, gt=0, le=60_000)
    observed_at_ms: int | None = Field(default=None, ge=0)
    track_id: str | None = Field(default=None, max_length=64)
    model_version: str | None = Field(default=None, max_length=64)
    pose_class: str | None = Field(default=None, max_length=32)
    pose: dict[str, float] | None = None
    bbox: dict[str, int] | None = None


class PersonDetectionDelivery(BaseModel):
    robot_id: str
    delivered: bool
