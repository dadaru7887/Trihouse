"""RMF dispatch worker whose durable state is owned by the FMS Gateway."""

from __future__ import annotations

import time

from dataclasses import dataclass
from typing import Callable, Any, Mapping, Protocol

from control_tower.gateway.fms_client import (
    RmfDispatchAcceptanceRequest,
    RmfDispatchClaimRequest,
    RmfDispatchGatewayClient,
    StepDispatchResponse,
)

from .task_api import (
    DispatchAcceptance,
    GoToPlaceRequest,
    build_dispatch_request,
)


class TaskApiTransport(Protocol):
    def submit(
        self,
        request_id: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> DispatchAcceptance: ...


@dataclass(frozen=True)
class RmfGatewayWorkerReport:
    claimed: int = 0
    accepted: int = 0
    rejected: int = 0
    indeterminate: int = 0


class RmfGatewayWorker:
    """Claim RMF messages over HTTP, submit to ROS, and report over HTTP."""

    def __init__(
        self,
        gateway: RmfDispatchGatewayClient,
        transport: TaskApiTransport,
        *,
        worker_id: str,
        default_fleet_name: str,
        timeout_s: float = 5.0,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        if not worker_id.strip() or not default_fleet_name.strip():
            raise ValueError("worker_id and default_fleet_name are required")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._gateway = gateway
        self._transport = transport
        self._worker_id = worker_id
        self._default_fleet_name = default_fleet_name
        self._timeout_s = timeout_s
        # RMF 와 같은 시계여야 한다. 시뮬에서 fleet adapter 는 use_sim_time 으로
        # 돌므로 원장의 벽시계를 시작 시각으로 보내면 그 작업은 수십 년 뒤에나
        # 시작할 수 있는 것이 된다. 주지 않으면 벽시계를 쓴다 — 실기는 두 시계가
        # 같아서 그것으로 맞다.
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))

    def run_once(self, *, limit: int = 10) -> RmfGatewayWorkerReport:
        claimed = self._gateway.claim_rmf_dispatches(
            RmfDispatchClaimRequest(worker_id=self._worker_id, limit=limit)
        ).dispatches
        accepted = rejected = indeterminate = 0
        for dispatch in claimed:
            try:
                request = self._to_rmf_request(dispatch)
            except ValueError as error:
                self._reject(dispatch.message_id, f"INVALID_RMF_DISPATCH: {error}")
                rejected += 1
                continue
            try:
                result = self._transport.submit(
                    dispatch.message_id,
                    build_dispatch_request(request),
                    self._timeout_s,
                )
            except Exception as error:
                # publish 뒤 timeout/transport error는 RMF 미접수의 증거가 아니다.
                # 같은 request_id의 booking을 조회·취소하기 전까지 sent 상태를
                # 유지해 중복 task 제출을 차단한다.
                indeterminate += 1
                continue
            if not result.accepted:
                detail = result.reason_code or "RMF_TASK_REJECTED"
                if result.detail:
                    detail = f"{detail}: {result.detail}"
                self._reject(dispatch.message_id, detail)
                rejected += 1
                continue
            if (
                result.assignment is not None
                and result.assignment.robot_name != request.robot_name
            ):
                # RMF가 다른 Pinky를 낙찰하면 그 관측으로 Control Tower의
                # jobs.assigned_mobile_id를 덮어쓰지 않는다. 배정을 유지한 채
                # message만 거절해 잘못된 로봇의 실행을 차단한다.
                self._reject(
                    dispatch.message_id,
                    f"ASSIGNMENT_MISMATCH: expected {request.robot_name}, "
                    f"RMF assigned {result.assignment.robot_name}",
                )
                rejected += 1
                continue
            if result.assignment is None:
                # RMF가 booking을 이미 수락했으므로 FMS message를 failed로
                # 확정하면 나중에 실제 로봇이 움직여도 추적할 수 없다. assignment
                # observer/cancel 확인 전까지 sent 상태를 유지해 실행을 차단한다.
                self._gateway.report_rmf_acceptance(
                    dispatch.message_id,
                    RmfDispatchAcceptanceRequest(
                        accepted=False,
                        rmf_task_id=result.rmf_task_id,
                        detail="RMF_ASSIGNMENT_PENDING",
                    ),
                )
                indeterminate += 1
                continue
            assigned_device_id = result.assignment.robot_name
            self._gateway.report_rmf_acceptance(
                dispatch.message_id,
                RmfDispatchAcceptanceRequest(
                    accepted=True,
                    rmf_task_id=result.rmf_task_id,
                    assigned_device_id=assigned_device_id,
                    detail=result.rmf_status or None,
                ),
            )
            accepted += 1
        return RmfGatewayWorkerReport(
            claimed=len(claimed),
            accepted=accepted,
            rejected=rejected,
            indeterminate=indeterminate,
        )

    def _to_rmf_request(self, dispatch: StepDispatchResponse) -> GoToPlaceRequest:
        payload = dispatch.payload
        waypoint = _text(payload.get("target_waypoint"))
        if not waypoint:
            raise ValueError("target_waypoint is required")
        fleet_name = _text(payload.get("fleet_name")) or self._default_fleet_name
        request = payload.get("request")
        assigned_device_id = (
            _text(request.get("assigned_device_id"))
            if isinstance(request, Mapping)
            else ""
        )
        if not assigned_device_id:
            raise ValueError("assigned_device_id is required")
        request_time_ms = payload.get("request_time_ms")
        if not isinstance(request_time_ms, int) or isinstance(request_time_ms, bool):
            raise ValueError("request_time_ms must be an integer")
        return GoToPlaceRequest(
            request_id=dispatch.message_id,
            job_step_id=dispatch.job_step_id,
            waypoint=waypoint,
            fleet_name=fleet_name,
            robot_name=assigned_device_id,
            request_time_ms=request_time_ms,
            earliest_start_time_ms=self._now_ms(),
        )

    def _reject(self, message_id: str, detail: str) -> None:
        self._gateway.report_rmf_acceptance(
            message_id,
            RmfDispatchAcceptanceRequest(accepted=False, detail=detail),
        )

def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
