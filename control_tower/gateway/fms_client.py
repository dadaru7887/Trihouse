"""Typed HTTP boundary from Control Tower to the FMS Gateway."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import OpenerDirector, Request, build_opener


JsonObject = dict[str, Any]


@dataclass(frozen=True)
class JobStepCreateRequest:
    step_no: int
    action_type: str
    executor_type: str
    target_location_id: int | None = None
    input: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class JobCreateRequest:
    job_code: str
    steps: tuple[JobStepCreateRequest, ...]
    operation_type: str = "outbound"
    priority: str = "normal"
    requested_by: str | None = None
    external_reference: str | None = None
    source_location_id: int | None = None
    destination_location_id: int | None = None
    due_at: str | None = None
    context: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class JobStepResponse:
    job_step_id: int
    step_no: int
    action_type: str
    executor_type: str
    target_location_id: int | None
    state: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "JobStepResponse":
        return cls(**{name: value.get(name) for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class JobCreateResponse:
    job_id: int
    job_code: str
    state: str
    steps: tuple[JobStepResponse, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "JobCreateResponse":
        return cls(
            job_id=int(value["job_id"]),
            job_code=str(value["job_code"]),
            state=str(value["state"]),
            steps=tuple(JobStepResponse.from_dict(step) for step in value["steps"]),
        )


@dataclass(frozen=True)
class StepDispatchRequest:
    idempotency_key: str
    actor: str
    occurred_at: str | None = None
    assigned_device_id: str | None = None
    retry: bool = False


@dataclass(frozen=True)
class StepDispatchResponse:
    message_id: str
    idempotency_key: str
    job_id: int
    job_step_id: int
    channel: str
    message_type: str
    state: str
    payload: JsonObject

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StepDispatchResponse":
        return cls(**{name: value[name] for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class DeviceSummary:
    """One registered device as the Gateway projects it for planning."""

    device_id: str
    device_type: str
    control_mode: str
    state: str | None = None
    health: str | None = None
    navigation_state: int | None = None
    current_job_step_id: int | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DeviceSummary":
        return cls(**{name: value.get(name) for name in cls.__dataclass_fields__})

    @property
    def assignable(self) -> bool:
        """Mirror the Gateway's availability rule without owning it.

        The Gateway re-checks this under a row lock and is the authority.  The
        runner only uses it to avoid proposing an assignment that is certain to
        be rejected.
        """
        return (
            self.control_mode == "automatic"
            and self.state in {"idle", "charging"}
            and self.health == "ok"
        )


@dataclass(frozen=True)
class JobSummary:
    """Job list projection used to find work that still needs advancing."""

    job_id: int
    job_code: str
    state: str
    operation_type: str = "outbound"
    priority: str = "normal"
    assigned_mobile_id: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "JobSummary":
        return cls(**{name: value.get(name) for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class JobStepDetail:
    """One persisted step with the state the runner sequences on."""

    job_step_id: int
    step_no: int
    action_type: str
    executor_type: str
    state: str
    target_location_id: int | None = None
    assigned_device_id: str | None = None
    input: JsonObject = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "JobStepDetail":
        return cls(**{name: value.get(name) for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class JobDetailResponse:
    """Full job projection: the runner reads context and ordered steps here."""

    job_id: int
    job_code: str
    state: str
    context: JsonObject = field(default_factory=dict)
    steps: tuple[JobStepDetail, ...] = ()
    # 적재 증거는 품목마다 하나씩 낸다. 그 목록이 없으면 실행기가 무엇에 대해
    # 증거를 내야 하는지 알 수 없다.
    items: tuple[JsonObject, ...] = ()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "JobDetailResponse":
        return cls(
            job_id=int(value["job_id"]),
            job_code=str(value["job_code"]),
            state=str(value["state"]),
            context=dict(value.get("context") or {}),
            steps=tuple(
                JobStepDetail.from_dict(step) for step in value.get("steps") or ()
            ),
            items=tuple(dict(item) for item in value.get("items") or ()),
        )


@dataclass(frozen=True)
class JobAssignmentRequest:
    """One complete Control Tower selection; the Gateway persists it atomically."""

    revision: int
    mobile_id: str
    omx_id: str
    packing_dock_code: str
    charger_code: str
    omx_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized = self.omx_ids or (self.omx_id,)
        if len(normalized) != len(set(normalized)) or self.omx_id not in normalized:
            raise ValueError("omx_ids must be unique and include omx_id")
        object.__setattr__(self, "omx_ids", tuple(normalized))


@dataclass(frozen=True)
class JobAssignmentResponse:
    job_id: int
    revision: int
    mobile_id: str
    omx_id: str
    packing_dock_code: str
    charger_code: str
    omx_ids: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "JobAssignmentResponse":
        return cls(
            job_id=int(value["job_id"]),
            revision=int(value["revision"]),
            mobile_id=str(value["mobile_id"]),
            omx_id=str(value["omx_id"]),
            packing_dock_code=str(value["packing_dock_code"]),
            charger_code=str(value["charger_code"]),
            omx_ids=tuple(value.get("omx_ids") or (value["omx_id"],)),
        )


@dataclass(frozen=True)
class RmfDispatchClaimRequest:
    worker_id: str
    limit: int = 10


@dataclass(frozen=True)
class RmfDispatchClaimResponse:
    dispatches: tuple[StepDispatchResponse, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RmfDispatchClaimResponse":
        return cls(
            dispatches=tuple(
                StepDispatchResponse.from_dict(dispatch)
                for dispatch in value["dispatches"]
            )
        )


@dataclass(frozen=True)
class ExecutorDispatch:
    """One claimed outbox message plus the step context needed to act on it."""

    message_id: str
    job_id: int
    job_step_id: int
    channel: str
    message_type: str
    action_type: str
    executor_type: str
    payload: JsonObject = field(default_factory=dict)
    assigned_device_id: str | None = None
    assignment_revision: int = 0
    assignment: JsonObject = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutorDispatch":
        return cls(**{name: value.get(name) for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class ExecutorDispatchClaimRequest:
    worker_id: str
    channels: tuple[str, ...]
    limit: int = 10


@dataclass(frozen=True)
class StepOutcomeRequest:
    """Terminal report for one non-mobile step."""

    outcome: str
    assignment_revision: int
    method_code: str
    actor_device_id: str | None = None
    reason_code: str | None = None
    failure_domain: str = "none"
    detail: str | None = None
    metrics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class LoadAttemptRequest:
    """One item's fixture-observed load evidence; never an arm motion request.

    `observations` 는 지어낸 값이 아니라 로봇이 실제로 보고한 화물 상태여야
    한다. 그래야 원장에 남는 "실렸다" 가 관측에 근거한 기록이 된다.
    """

    attempt_id: str
    job_id: int
    item_id: int
    handover_group_id: str
    assignment_revision: int
    pinky_id: str
    omx_id: str
    result: str
    criteria: JsonObject
    observations: JsonObject
    # 아래 여섯은 Gateway 가 **모두 필수**로 요구한다. 하나라도 빠지면 422 다.
    # `evidence_refs` 는 최소 한 개여야 한다(빈 목록도 거절).
    metrics: JsonObject
    evidence_refs: tuple[str, ...]
    policy_name: str
    policy_version: str
    model_name: str
    model_version: str


@dataclass(frozen=True)
class LoadAttemptResponse:
    departure_allowed: bool

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LoadAttemptResponse":
        return cls(departure_allowed=bool(value.get("departure_allowed", False)))


@dataclass(frozen=True)
class StepOutcomeResponse:
    job_step_id: int
    job_id: int
    state: str
    attempt_uuid: str
    attempt_no: int

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StepOutcomeResponse":
        return cls(**{name: value[name] for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class RmfDispatchAcceptanceRequest:
    accepted: bool
    rmf_task_id: str | None = None
    assigned_device_id: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class RmfDispatchAcceptanceResponse:
    message_id: str
    job_step_id: int
    state: str
    rmf_task_id: str | None

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "RmfDispatchAcceptanceResponse":
        return cls(**{name: value.get(name) for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class RmfTaskUpdateRequest:
    """RMF 가 관측한 task 진행 상태. 입찰이 끝난 뒤의 배정이 여기 실려 온다."""

    rmf_task_id: str
    fleet_name: str
    robot_name: str
    rmf_status: str
    step_state: str
    observed_at_ms: int
    detail: str = ""


@dataclass(frozen=True)
class RmfTaskUpdateResponse:
    rmf_task_id: str
    job_step_id: int
    assigned_device_id: str | None
    settled: bool

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RmfTaskUpdateResponse":
        return cls(**{name: value.get(name) for name in cls.__dataclass_fields__})


class FMSGatewayClient(Protocol):
    """Dependency injected into Control Tower orchestration runtime."""

    def create_job(self, request: JobCreateRequest) -> JobCreateResponse: ...

    def dispatch_step(
        self,
        job_step_id: int,
        request: StepDispatchRequest,
    ) -> StepDispatchResponse: ...


class JobRunnerGatewayClient(Protocol):
    """Read/advance boundary required by the standalone job runner.

    Deliberately HTTP-only: the runner never reaches the database, so the
    Gateway stays the single writer and the single arbiter of resource
    reservations.
    """

    def list_devices(self) -> tuple[DeviceSummary, ...]: ...

    def list_jobs(self) -> tuple[JobSummary, ...]: ...

    def get_job(self, job_id: int) -> JobDetailResponse | None: ...

    def assign_job_resources(
        self,
        job_id: int,
        request: JobAssignmentRequest,
    ) -> JobAssignmentResponse: ...

    def dispatch_step(
        self,
        job_step_id: int,
        request: StepDispatchRequest,
    ) -> StepDispatchResponse: ...


class ExecutorGatewayClient(Protocol):
    """Outbox boundary required by the OMX/FMS executor worker."""

    def claim_executor_dispatches(
        self,
        request: ExecutorDispatchClaimRequest,
    ) -> tuple[ExecutorDispatch, ...]: ...

    def record_executor_outcome(
        self,
        job_step_id: int,
        request: StepOutcomeRequest,
        *,
        idempotency_key: str,
    ) -> StepOutcomeResponse: ...

    def record_load_attempt(
        self,
        job_step_id: int,
        request: LoadAttemptRequest,
        *,
        idempotency_key: str,
    ) -> LoadAttemptResponse: ...


class RmfDispatchGatewayClient(Protocol):
    """FMS outbox boundary required by the standalone RMF worker."""

    def claim_rmf_dispatches(
        self,
        request: RmfDispatchClaimRequest,
    ) -> RmfDispatchClaimResponse: ...

    def report_rmf_acceptance(
        self,
        message_id: str,
        request: RmfDispatchAcceptanceRequest,
    ) -> RmfDispatchAcceptanceResponse: ...


class FMSGatewayHttpClient:
    """Small stdlib HTTP implementation of the FMS Gateway protocol."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 5.0,
        opener: OpenerDirector | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._opener = opener or build_opener()

    def create_job(self, request: JobCreateRequest) -> JobCreateResponse:
        payload = _omit_none(asdict(request))
        response = self._post("/internal/v1/jobs", payload)
        return JobCreateResponse.from_dict(response)

    def dispatch_step(
        self,
        job_step_id: int,
        request: StepDispatchRequest,
    ) -> StepDispatchResponse:
        payload = _omit_none(asdict(request))
        idempotency_key = str(payload.pop("idempotency_key"))
        response = self._post(
            f"/internal/v1/job-steps/{job_step_id}/dispatch",
            payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        return StepDispatchResponse.from_dict(response)

    def list_devices(self) -> tuple[DeviceSummary, ...]:
        response = self._get("/api/v1/devices")
        return tuple(DeviceSummary.from_dict(device) for device in response)

    def list_jobs(self) -> tuple[JobSummary, ...]:
        response = self._get("/api/v1/jobs")
        return tuple(JobSummary.from_dict(job) for job in response)

    def get_job(self, job_id: int) -> JobDetailResponse | None:
        response = self._get(f"/api/v1/jobs/{job_id}", allow_missing=True)
        if response is None:
            return None
        return JobDetailResponse.from_dict(response)

    def assign_job_resources(
        self,
        job_id: int,
        request: JobAssignmentRequest,
    ) -> JobAssignmentResponse:
        response = self._post(
            f"/internal/v1/jobs/{job_id}/assignment",
            _omit_none(asdict(request)),
        )
        return JobAssignmentResponse.from_dict(response)

    def claim_executor_dispatches(
        self,
        request: ExecutorDispatchClaimRequest,
    ) -> tuple[ExecutorDispatch, ...]:
        response = self._post(
            "/internal/v1/executor/dispatches/claim",
            {
                "worker_id": request.worker_id,
                "channels": list(request.channels),
                "limit": request.limit,
            },
        )
        return tuple(
            ExecutorDispatch.from_dict(dispatch)
            for dispatch in response["dispatches"]
        )

    def record_executor_outcome(
        self,
        job_step_id: int,
        request: StepOutcomeRequest,
        *,
        idempotency_key: str,
    ) -> StepOutcomeResponse:
        response = self._post(
            f"/internal/v1/job-steps/{job_step_id}/outcome",
            _omit_none(asdict(request)),
            headers={"Idempotency-Key": idempotency_key},
        )
        return StepOutcomeResponse.from_dict(response)

    def record_load_attempt(
        self,
        job_step_id: int,
        request: LoadAttemptRequest,
        *,
        idempotency_key: str,
    ) -> LoadAttemptResponse:
        response = self._post(
            f"/internal/v1/job-steps/{job_step_id}/load-attempts",
            _omit_none(asdict(request)),
            headers={"Idempotency-Key": idempotency_key},
        )
        return LoadAttemptResponse.from_dict(response)

    def claim_rmf_dispatches(
        self,
        request: RmfDispatchClaimRequest,
    ) -> RmfDispatchClaimResponse:
        response = self._post(
            "/internal/v1/rmf/dispatches/claim",
            _omit_none(asdict(request)),
        )
        return RmfDispatchClaimResponse.from_dict(response)

    def report_rmf_acceptance(
        self,
        message_id: str,
        request: RmfDispatchAcceptanceRequest,
    ) -> RmfDispatchAcceptanceResponse:
        response = self._post(
            f"/internal/v1/rmf/dispatches/{quote(message_id, safe='')}/acceptance",
            _omit_none(asdict(request)),
        )
        return RmfDispatchAcceptanceResponse.from_dict(response)

    def apply_rmf_task_update(
        self, request: RmfTaskUpdateRequest
    ) -> RmfTaskUpdateResponse | None:
        """관측한 배정을 원장에 반영한다. 우리 task 가 아니면 None 을 돌려준다.

        TaskSummary 는 fleet 전체의 것이 온다. 남의 task 까지 반영하려 들면
        엉뚱한 step 에 로봇을 쓰게 되므로, 아는 task 인지는 Gateway 가 판단한다.
        """
        body = _omit_none(asdict(request))
        body.pop("rmf_task_id", None)
        response = self._post_optional(
            f"/internal/v1/rmf/tasks/{quote(request.rmf_task_id, safe='')}/updates",
            body,
        )
        if response is None:
            return None
        return RmfTaskUpdateResponse.from_dict(response)

    def cancel_job(
        self,
        job_id: int,
        *,
        reason: str,
        requested_by: str,
        idempotency_key: str,
    ) -> JsonObject:
        """Close a job and hand every resource it was holding back.

        RMF 에 제출되기 전에 멈춘 job 은 `rmf_task_repository` 의 해제 경로를 타지
        못해 로봇·팔·Dock 을 영원히 쥔다. 원장을 손으로 고치는 대신 이 경로를 쓴다.
        """
        return self._post(
            f"/internal/v1/jobs/{job_id}/cancel",
            {"reason": reason, "requested_by": requested_by},
            headers={"Idempotency-Key": idempotency_key},
        )

    def expire_reservations(self) -> JsonObject:
        """Sweep overdue reservations back into the pool before assigning again."""
        return self._post("/internal/v1/reservations/expire", {})

    def list_open_anomalies(self) -> tuple[JsonObject, ...]:
        return tuple(self._get("/api/v1/operations/anomalies?state=open"))

    def acknowledge_anomaly(
        self, correlation_uuid: str, *, worker_id: str, note: str
    ) -> JsonObject:
        """사람이 그 이상을 봤다고 원장에 적는다.

        열려 있지 않은 것을 닫으려 하면 `LookupError` 를 낸다 — 관제 UI 서버가 그
        예외를 404 로 옮긴다.
        """
        try:
            return self._post(
                "/api/v1/operations/anomalies/"
                f"{quote(correlation_uuid, safe='')}/acknowledge",
                {"worker_id": worker_id, "note": note},
            )
        except HTTPError as error:
            if error.code == 404:
                raise LookupError(correlation_uuid) from error
            raise

    def _get(self, path: str, *, allow_missing: bool = False) -> Any:
        request = Request(f"{self._base_url}{path}", method="GET")
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                return json.loads(response.read())
        except HTTPError as error:
            # A job that vanished between listing and reading is normal in a
            # polling loop; anything else is a real fault worth raising.
            if allow_missing and error.code == 404:
                return None
            raise

    def _post(
        self,
        path: str,
        payload: JsonObject,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(headers or {})
        request = Request(
            f"{self._base_url}{path}",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        with self._opener.open(request, timeout=self._timeout) as response:
            return json.loads(response.read())

    def _post_optional(
        self,
        path: str,
        payload: JsonObject,
    ) -> JsonObject | None:
        """404 는 오류가 아니라 "우리 것이 아니다" 라는 답이다."""
        request = Request(
            f"{self._base_url}{path}",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if getattr(response, "status", 200) == 404:
                    return None
                return json.loads(response.read())
        except HTTPError as error:
            if error.code == 404:
                return None
            raise


def _omit_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _omit_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, (list, tuple)):
        return [_omit_none(item) for item in value]
    return value
