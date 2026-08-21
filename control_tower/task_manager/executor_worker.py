"""Execute the OMX and FMS half of a Job and report each step's outcome.

`rmf_gateway_worker` carries `mobile` steps to RMF, and the robot closes them
through its own `task_event` stream. The other two channels had neither half:
nothing claimed an `omx` or `pinky` outbox row, and no code path moved those
steps out of `pending`. An order therefore stopped at its first `pick` and the
navigation that follows was never dispatched.

The same three properties as `job_runner` are deliberate.

**Stateless across cycles.** What work is outstanding is re-read from the
Gateway every cycle. The one thing this process does keep is each arm's
physical state (`PREPARING`/`PICKING`/`OMX_READY`), because that belongs to the
equipment rather than to the plan — a real arm does not store its pose in the
database either. Job progress never depends on it, so a restart resumes from
whatever the Gateway says and re-synchronises the arm with a `reset`.

**Stable idempotency keys.** Outcome keys are derived from step identity and
attempt, so a report that is retried after a lost response returns the original
answer instead of closing the step twice.

**The Gateway stays the arbiter.** This worker decides what happened; it does
not decide whether the step was allowed to finish. Assignment revision, step
state, and per-item load confirmation are all re-checked server-side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

import uuid

from control_tower.gateway.fms_client import (
    ExecutorDispatch,
    ExecutorDispatchClaimRequest,
    ExecutorGatewayClient,
    LoadAttemptRequest,
    StepOutcomeRequest,
)


# Channels this worker owns. `rmf` belongs to `rmf_gateway_worker`.
EXECUTOR_CHANNELS = ("omx", "pinky")

# 적재로 인정하는 화물 상태. `CargoState.STATE_LOCKED` 다. 로봇이 잠갔다고
# 말하는 것과 센서가 확인한 것은 다른 사실이라 둘 다 요구한다.
CARGO_STATE_LOCKED = 2


class _LoadNotConfirmedYet(Exception):
    """화물이 아직 실리지 않았다. **실패가 아니라 대기다.**

    로봇이 도착하면 로봇팔이 적재를 시작하고, 그것이 끝나 원장에 닿기까지 시간이
    걸린다(2026-08-19 실측: 도착 0.6초 뒤 확인했더니 아직 안 실려 있었고 1.4초
    뒤에 끝났다). 그 사이의 조회를 실패로 적으면 운영자가 없는 문제를 쫓는다."""

# `wait` is excluded on purpose: a packing worker closes it through
# `POST /api/v1/jobs/{id}/worker-completion`, and a background process must
# never sign off work a human is supposed to confirm.
WORKER_CONFIRMED_ACTIONS = frozenset({"wait"})


class OmxSimulator(Protocol):
    """The deterministic arm contract this worker drives."""

    @property
    def state(self) -> str: ...

    def execute(self, command: dict[str, object]) -> tuple[object, ...]: ...


@dataclass(frozen=True)
class ExecutorReport:
    claimed: int = 0
    succeeded: tuple[int, ...] = ()
    failed: tuple[int, ...] = ()
    deferred: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.succeeded or self.failed)


@dataclass
class _Cycle:
    claimed: int = 0
    succeeded: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def report(self) -> ExecutorReport:
        return ExecutorReport(
            claimed=self.claimed,
            succeeded=tuple(self.succeeded),
            failed=tuple(self.failed),
            deferred=tuple(self.deferred),
            errors=tuple(self.errors),
        )


class ExecutorWorker:
    """Claim OMX/FMS dispatches, run them, and report the result."""

    def __init__(
        self,
        gateway: ExecutorGatewayClient,
        *,
        simulators: dict[str, OmxSimulator],
        worker_id: str = "control-tower-executor",
        environment: str = "simulation",
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._gateway = gateway
        self._simulators = dict(simulators)
        self._worker_id = worker_id
        self._environment = environment
        self._clock_ms = clock_ms or _monotonic_ms

    def run_once(self, *, limit: int = 10) -> ExecutorReport:
        if limit <= 0:
            raise ValueError("limit must be positive")
        cycle = _Cycle()
        dispatches = self._gateway.claim_executor_dispatches(
            ExecutorDispatchClaimRequest(
                worker_id=self._worker_id,
                channels=EXECUTOR_CHANNELS,
                limit=limit,
            )
        )
        cycle.claimed = len(dispatches)
        for dispatch in dispatches:
            try:
                self._run(dispatch, cycle)
            except Exception as error:  # noqa: BLE001
                # One bad dispatch must not stop the cycle; the Gateway will
                # hand it back on a later poll. Recorded so it stays visible.
                cycle.errors.append(f"step {dispatch.job_step_id}: {error}")
        return cycle.report()

    def _run(self, dispatch: ExecutorDispatch, cycle: _Cycle) -> None:
        if dispatch.action_type in WORKER_CONFIRMED_ACTIONS:
            cycle.deferred.append(
                f"step {dispatch.job_step_id}: {dispatch.action_type} awaits the worker"
            )
            return

        started_ms = self._clock_ms()
        if dispatch.executor_type == "arm":
            segments = self._run_arm(dispatch)
            method_code = "OMX_SIMULATED_CONTRACT"
        else:
            try:
                segments = self._run_fms(dispatch)
            except _LoadNotConfirmedYet as waiting:
                # 아직 실리지 않았다. 이 주기에는 아무것도 적지 않고 다음에 다시 본다.
                cycle.deferred.append(f"step {dispatch.job_step_id}: {waiting}")
                return
            method_code = "FMS_SIMULATED_CONTRACT"
        total_ms = max(self._clock_ms() - started_ms, 0)

        response = self._gateway.record_executor_outcome(
            dispatch.job_step_id,
            StepOutcomeRequest(
                outcome="succeeded",
                assignment_revision=dispatch.assignment_revision,
                method_code=method_code,
                actor_device_id=self._actor_device(dispatch),
                reason_code=f"{dispatch.action_type.upper()}_CONFIRMED",
                metrics=self._metrics(total_ms, segments),
            ),
            idempotency_key=_outcome_key(dispatch),
        )
        if response.state == "succeeded":
            cycle.succeeded.append(dispatch.job_step_id)
        else:
            cycle.failed.append(dispatch.job_step_id)

    def _run_arm(self, dispatch: ExecutorDispatch) -> dict[str, int]:
        """Drive the arm through its own contract rather than faking a result."""
        omx_id = self._actor_device(dispatch)
        simulator = self._simulators.get(omx_id or "")
        if simulator is None:
            raise LookupError(f"no simulator is configured for {omx_id!r}")
        started_ms = self._clock_ms()
        simulator.execute(
            {
                "command_uuid": _command_uuid(dispatch),
                "kind": "prepare",
                "job_step_id": dispatch.job_step_id,
                "assignment_revision": dispatch.assignment_revision,
                "omx_id": omx_id,
                "expected_items": _expected_items(dispatch),
                "marker_id": _marker_id(dispatch),
            }
        )
        return {"grasp_ms": max(self._clock_ms() - started_ms, 0)}

    def _run_fms(self, dispatch: ExecutorDispatch) -> dict[str, int]:
        """`load` and `handover` are bookkeeping transitions in P0.

        No physical motion belongs to the FMS itself: the arm has already placed
        the item, and this step records that the transfer is accounted for. The
        segment is still measured so the duration model has a real sample rather
        than an assumed zero.

        `load` 만은 장부만으로 끝나지 않는다. Gateway 는 품목마다
        `load_result = LOAD_CONFIRMED` 를 요구하고, 그 증거를 내는 곳이 없으면
        step 이 `LOAD_ITEMS_NOT_CONFIRMED` 로 영원히 닫히지 않는다
        (2026-08-19 실측). 여기서 로봇이 실제로 보고한 화물 상태를 읽어
        증거로 제출한다 — **관측이 없으면 제출하지 않는다.**
        """
        started_ms = self._clock_ms()
        if dispatch.action_type == "load":
            self._run_arm_load(dispatch)
            self._confirm_load(dispatch)
        return {"transfer_ms": max(self._clock_ms() - started_ms, 0)}

    def _run_arm_load(self, dispatch: ExecutorDispatch) -> None:
        """Authorize the prepared OMX to transfer its item to Pinky.

        ``load`` is issued only after the Gateway has released Step 30, whose
        dependencies require both the OMX preparation step and Pinky's
        navigation step to have succeeded.  The simulator (and the eventual
        hardware adapter) rejects it unless the same OMX is still ``OMX_READY``.
        Its command UUID is stable, so polling Step 30 again cannot repeat a
        physical transfer after a delayed cargo confirmation.
        """
        omx_id = _omx_id_for_dispatch(dispatch)
        if omx_id is None:
            raise LookupError(f"load step {dispatch.job_step_id} is missing OMX identity")
        simulator = self._simulators.get(omx_id)
        if simulator is None:
            raise LookupError(f"no simulator is configured for {omx_id!r}")
        simulator.execute(
            {
                "command_uuid": _command_uuid(dispatch),
                "kind": "load",
                "job_step_id": dispatch.job_step_id,
                "assignment_revision": dispatch.assignment_revision,
                "omx_id": omx_id,
                "expected_items": _expected_items(dispatch),
                "marker_id": _marker_id(dispatch),
            }
        )

    def _confirm_load(self, dispatch: ExecutorDispatch) -> None:
        """로봇의 화물 관측을 품목별 적재 증거로 옮긴다."""
        step_input = dispatch.payload.get("input") or {}
        handover_group_id = step_input.get("handover_group_id")
        pinky_id = dispatch.assignment.get("mobile_id") or dispatch.assigned_device_id
        omx_id = _omx_id_for_dispatch(dispatch)
        if not (handover_group_id and pinky_id and omx_id):
            raise LookupError(
                f"load step {dispatch.job_step_id} is missing handover identity"
            )

        observed = self._robot_observation(str(pinky_id))
        # 관측이 적재를 말하지 않으면 아무것도 적지 않는다. step 은 열린 채로
        # 남고 다음 주기에 다시 본다 — 거짓 적재를 원장에 넣는 것보다 낫다.
        confirmed = (
            observed.cargo_state == CARGO_STATE_LOCKED
            and observed.cargo_sensor_confirmed is True
        )
        if not confirmed:
            raise _LoadNotConfirmedYet(
                f"{pinky_id} 적재 대기 중 "
                f"(cargo_state={observed.cargo_state}, "
                f"sensor_confirmed={observed.cargo_sensor_confirmed})"
            )

        job = self._gateway.get_job(dispatch.job_id)
        if job is None:
            raise LookupError(f"job {dispatch.job_id} is not in the ledger")
        if not job.items:
            raise LookupError(f"job {dispatch.job_id} has no items to confirm")
        for item in job.items:
            item_id = item.get("job_item_id")
            if item_id is None:
                continue
            key = f"load:{dispatch.job_step_id}:{dispatch.assignment_revision}:{item_id}"
            self._gateway.record_load_attempt(
                dispatch.job_step_id,
                LoadAttemptRequest(
                    # 같은 키에는 같은 시도 식별자여야 재전송이 멱등하다.
                    attempt_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"trihouse:{key}")),
                    job_id=int(dispatch.job_id),
                    item_id=int(item_id),
                    handover_group_id=str(handover_group_id),
                    assignment_revision=int(dispatch.assignment_revision),
                    pinky_id=str(pinky_id),
                    omx_id=str(omx_id),
                    result="LOAD_CONFIRMED",
                    criteria={
                        "cargo_locked": True,
                        "cargo_sensor_confirmed": True,
                    },
                    observations={
                        "cargo_state": observed.cargo_state,
                        "cargo_sensor_confirmed": observed.cargo_sensor_confirmed,
                        "navigation_state": observed.navigation_state,
                        "device_state": observed.state,
                    },
                    metrics={"environment": self._environment},
                    # 아직 이미지·ROS bag 을 남기지 않는다. 무엇을 근거로 판단했는지는
                    # 남겨야 하므로 관측을 낸 장치를 참조로 적는다. 카메라가 붙으면
                    # 그때 실제 프레임 참조로 바꾼다.
                    evidence_refs=(f"device_state:{pinky_id}",),
                    # 이 판단을 누가 했는지. 지금은 화물 센서 게이트라는 규칙이다.
                    # ACT 정책이 붙으면 그 이름과 버전이 여기 들어간다.
                    policy_name="cargo-sensor-gate",
                    policy_version="p0-v1",
                    model_name="none",
                    model_version="none",
                ),
                idempotency_key=key,
            )

    def _robot_observation(self, device_id: str):
        """원장이 아는 그 로봇의 최신 관측. `DeviceSummary` 를 그대로 돌려준다."""
        for device in self._gateway.list_devices():
            if device.device_id == device_id:
                return device
        raise LookupError(f"device {device_id!r} is not registered")

    def _metrics(self, total_ms: int, segments: dict[str, int]) -> dict[str, object]:
        """Record every candidate scope, aggregate on one.

        The chosen baseline axis is the temperature zone, but the axis may well
        turn out to be wrong. Writing all of them into the raw sample means a
        later change of mind re-aggregates history instead of discarding it.
        """
        return {
            "duration": {
                "total_ms": total_ms,
                "segments": dict(segments),
                "environment": self._environment,
                "attribution": "measured",
            }
        }

    @staticmethod
    def _actor_device(dispatch: ExecutorDispatch) -> str | None:
        if dispatch.executor_type == "arm":
            return _omx_id_for_dispatch(dispatch)
        if dispatch.assigned_device_id:
            return dispatch.assigned_device_id
        return None


def _omx_id_for_dispatch(dispatch: ExecutorDispatch) -> str | None:
    """Return the workcell pinned to this temperature-zone transfer.

    Older single-zone jobs do not carry ``input.omx_id``.  They keep using the
    job-level assignment during the migration, while mixed-zone jobs always
    prefer their explicit ZoneBundle workcell.
    """
    step_input = dispatch.payload.get("input") or {}
    omx_id = step_input.get("omx_id")
    if isinstance(omx_id, str) and omx_id:
        return omx_id
    # FMS load steps are assigned to Pinky for dispatch ownership, not OMX.
    # Only an arm step's assigned_device_id is an OMX fallback.
    if dispatch.executor_type == "arm" and dispatch.assigned_device_id:
        return dispatch.assigned_device_id
    omx_id = dispatch.assignment.get("omx_id")
    return omx_id if isinstance(omx_id, str) and omx_id else None


def _expected_items(dispatch: ExecutorDispatch) -> tuple[str, ...]:
    step_input = dispatch.payload.get("input") or {}
    items = step_input.get("expected_items") or step_input.get("items")
    if isinstance(items, (list, tuple)) and items:
        return tuple(str(item) for item in items)
    sku = step_input.get("sku") or step_input.get("product_code")
    return (str(sku),) if sku else (f"step-{dispatch.job_step_id}",)


def _marker_id(dispatch: ExecutorDispatch) -> int:
    step_input = dispatch.payload.get("input") or {}
    marker = step_input.get("marker_id")
    try:
        return int(marker)
    except (TypeError, ValueError):
        # The simulator only requires the field to be present and integral; P0
        # fixtures do not always carry a marker, and inventing a real ID would
        # be worse than a stable placeholder.
        return 0


def _command_uuid(dispatch: ExecutorDispatch) -> str:
    return f"omx-{dispatch.job_step_id}-rev-{dispatch.assignment_revision}"


def _outcome_key(dispatch: ExecutorDispatch) -> str:
    return (
        f"control-tower-executor-step-{dispatch.job_step_id}"
        f"-rev-{dispatch.assignment_revision}"
    )


def _monotonic_ms() -> int:
    from time import monotonic_ns

    return monotonic_ns() // 1_000_000


__all__ = [
    "EXECUTOR_CHANNELS",
    "ExecutorReport",
    "ExecutorWorker",
    "WORKER_CONFIRMED_ACTIONS",
]
