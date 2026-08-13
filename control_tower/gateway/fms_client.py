"""Typed HTTP boundary from Control Tower to the FMS Gateway."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Protocol
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


class FMSGatewayClient(Protocol):
    """Dependency injected into Control Tower orchestration runtime."""

    def create_job(self, request: JobCreateRequest) -> JobCreateResponse: ...

    def dispatch_step(
        self,
        job_step_id: int,
        request: StepDispatchRequest,
    ) -> StepDispatchResponse: ...


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


def _omit_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _omit_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, (list, tuple)):
        return [_omit_none(item) for item in value]
    return value
