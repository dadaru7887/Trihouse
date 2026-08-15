"""Public FMS API response models."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DeviceView(BaseModel):
    device_id: str
    device_type: str
    name: str
    control_mode: str
    state: str | None = None
    health: str | None = None
    battery_pct: float | None = None
    observed_at: datetime | None = None


class InventoryLotView(BaseModel):
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
    quantity_delta: int
    recorded_by: str = Field(min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=512)

    @field_validator("quantity_delta")
    @classmethod
    def quantity_must_change(cls, value: int) -> int:
        if value == 0:
            raise ValueError("quantity_delta must not be zero")
        return value


class JobView(BaseModel):
    job_id: int
    job_code: str
    operation_type: str
    priority: str
    state: str
    due_at: datetime | None = None
    assigned_mobile_id: str | None = None
    item_count: int
    step_count: int


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
    step_no: int = Field(ge=1, le=65535)
    action_type: ActionType
    executor_type: ExecutorType
    target_location_id: int | None = Field(default=None, ge=1)
    input: dict[str, Any] = Field(default_factory=dict)


class JobCreate(BaseModel):
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
    steps: list[dict[str, Any]]


class StepDispatch(BaseModel):
    actor: str = Field(min_length=1, max_length=64)
    occurred_at: datetime | None = None
    assigned_device_id: str | None = Field(default=None, max_length=64)
    retry: bool = False


class DispatchRecord(BaseModel):
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
    job_id: int
    events: list[TimelineEvent]


class CommandClaim(BaseModel):
    robot_id: str = Field(min_length=1, max_length=64)
    execution_id: str = Field(min_length=1, max_length=160)
    map_revision: str = Field(min_length=1, max_length=160)


class TaskContext(BaseModel):
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


class RmfDispatchClaim(BaseModel):
    worker_id: str = Field(min_length=1, max_length=64)
    limit: int = Field(default=1, ge=1, le=100)


class RmfDispatchesClaimed(BaseModel):
    dispatches: list[DispatchRecord]


class RmfDispatchAcceptance(BaseModel):
    accepted: bool
    rmf_task_id: str | None = Field(default=None, max_length=128)
    assigned_device_id: str | None = Field(default=None, max_length=64)
    detail: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def accepted_dispatch_requires_mapping(self):
        if self.accepted and not (self.rmf_task_id and self.assigned_device_id):
            raise ValueError("accepted dispatch requires rmf_task_id and assigned_device_id")
        return self


class RmfDispatchAccepted(BaseModel):
    message_id: str
    job_step_id: int
    state: str
    rmf_task_id: str | None = None


MapProjectSourceType = Literal[
    "slam_yaml",
    "slam_image",
    "floor_plan",
    "physical_features_import",
]


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
    metadata: dict[str, Any] | None = None
    created_at: datetime


class MapProjectFile(BaseModel):
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
