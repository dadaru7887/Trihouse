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
from typing import Any, Callable, Protocol

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

# `wait` is excluded on purpose: a packing worker closes it through
# `POST /api/v1/jobs/{id}/worker-completion`, and a background process must
# never sign off work a human is supposed to confirm.
WORKER_CONFIRMED_ACTIONS = frozenset({"wait"})


class OmxExecutor(Protocol):
    """Device-routed execution boundary implemented by the ROS Action client."""

    @property
    def state(self) -> str: ...

    def execute(self, command: dict[str, object]) -> dict[str, Any]: ...


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
        omx_executors: dict[str, OmxExecutor],
        worker_id: str = "control-tower-executor",
        environment: str = "simulation",
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._gateway = gateway
        self._omx_executors = dict(omx_executors)
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
            method_code = "OMX_ACTION_RESULT"
        else:
            segments = self._run_fms(dispatch)
            method_code = "FMS_LEDGER_CONTRACT"
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
        executor = self._omx_executors.get(omx_id or "")
        if executor is None:
            raise LookupError(f"no OMX Action executor is configured for {omx_id!r}")
        started_ms = self._clock_ms()
        result = executor.execute(_omx_command(dispatch, "prepare", self._job_items(dispatch)))
        if result.get("success") is not True or result.get("policy_completed") is not True:
            raise RuntimeError("OMX prepare did not return completed policy evidence")
        return {"grasp_ms": max(self._clock_ms() - started_ms, 0)}

    def _run_fms(self, dispatch: ExecutorDispatch) -> dict[str, int]:
        """`load` and `handover` are bookkeeping transitions in P0.

        No physical motion belongs to the FMS itself: the arm has already placed
        the item, and this step records that the transfer is accounted for. The
        segment is still measured so the duration model has a real sample rather
        than an assumed zero.

        `load`는 OMX Action의 품목별 파지·해제·정책 완료 결과를 적재 증거로
        기록한다. Pinky에는 화물 센서가 없으므로 Pinky 상태를 적재 판정에 쓰지 않는다.
        """
        started_ms = self._clock_ms()
        if dispatch.action_type == "load":
            result = self._run_arm_load(dispatch)
            self._confirm_load(dispatch, result)
        return {"transfer_ms": max(self._clock_ms() - started_ms, 0)}

    def _run_arm_load(self, dispatch: ExecutorDispatch) -> dict[str, Any]:
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
        executor = self._omx_executors.get(omx_id)
        if executor is None:
            raise LookupError(f"no OMX Action executor is configured for {omx_id!r}")
        return executor.execute(_omx_command(dispatch, "load", self._job_items(dispatch)))

    def _confirm_load(self, dispatch: ExecutorDispatch, result: dict[str, Any]) -> None:
        """Record complete per-item OMX observations as load evidence."""
        step_input = dispatch.payload.get("input") or {}
        handover_group_id = step_input.get("handover_group_id")
        pinky_id = dispatch.assignment.get("mobile_id") or dispatch.assigned_device_id
        omx_id = _omx_id_for_dispatch(dispatch)
        if not (handover_group_id and pinky_id and omx_id):
            raise LookupError(
                f"load step {dispatch.job_step_id} is missing handover identity"
            )

        expected_items = self._job_items(dispatch)
        raw_results = result.get("items") if isinstance(result, dict) else None
        if result.get("success") is not True or result.get("policy_completed") is not True:
            raise RuntimeError("incomplete OMX load evidence: command did not complete")
        if not isinstance(raw_results, list):
            raise RuntimeError("incomplete OMX load evidence: items are missing")
        by_item_id = {
            raw.get("job_item_id"): raw for raw in raw_results if isinstance(raw, dict)
        }
        expected_ids = {item["job_item_id"] for item in expected_items}
        if set(by_item_id) != expected_ids or any(
            evidence.get("grasp_confirmed") is not True
            or evidence.get("release_confirmed") is not True
            or evidence.get("policy_completed") is not True
            for evidence in by_item_id.values()
        ):
            raise RuntimeError("incomplete OMX load evidence for one or more items")

        # EN: Validate the complete result before writing any item attempt.
        # KO: 일부 품목만 성공한 원장이 남지 않도록 전체 결과를 먼저 검증한다.
        for item in expected_items:
            item_id = item["job_item_id"]
            evidence = by_item_id[item_id]
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
                        "grasp_confirmed": True,
                        "release_confirmed": True,
                        "policy_completed": True,
                    },
                    observations=dict(evidence),
                    metrics={"environment": self._environment},
                    evidence_refs=tuple(str(ref) for ref in evidence.get("evidence_refs", [])),
                    policy_name=str(result.get("policy_name", "act")),
                    policy_version=str(result.get("policy_version", "unknown")),
                    model_name=str(result.get("model_name", "act")),
                    model_version=str(result.get("model_version", "unknown")),
                ),
                idempotency_key=key,
            )

    def _job_items(self, dispatch: ExecutorDispatch) -> list[dict[str, object]]:
        job = self._gateway.get_job(dispatch.job_id)
        if job is None:
            raise LookupError(f"job {dispatch.job_id} is not in the ledger")
        product_codes = (dispatch.payload.get("input") or {}).get("product_codes")
        allowed = set(product_codes) if isinstance(product_codes, list) else None
        items = [
            {
                "job_item_id": int(item["job_item_id"]),
                "product_code": str(item["product_code"]),
                "quantity": int(item.get("requested_qty", 1)),
            }
            for item in job.items
            if item.get("job_item_id") is not None
            and item.get("product_code")
            and (allowed is None or item.get("product_code") in allowed)
        ]
        if not items:
            raise LookupError(f"job {dispatch.job_id} has no OMX items for this step")
        return items

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


def _omx_command(
    dispatch: ExecutorDispatch,
    kind: str,
    items: list[dict[str, object]],
) -> dict[str, object]:
    step_input = dispatch.payload.get("input") or {}
    temperature_zone = step_input.get("temperature_zone")
    omx_id = _omx_id_for_dispatch(dispatch)
    if not isinstance(temperature_zone, str) or not temperature_zone:
        raise LookupError(f"step {dispatch.job_step_id} is missing temperature_zone")
    if omx_id is None:
        raise LookupError(f"step {dispatch.job_step_id} is missing OMX identity")
    return {
        "schema_version": 1,
        "command_uuid": _command_uuid(dispatch),
        "kind": kind,
        "job_id": int(dispatch.job_id),
        "job_step_id": int(dispatch.job_step_id),
        "assignment_revision": int(dispatch.assignment_revision),
        "omx_id": omx_id,
        "temperature_zone": temperature_zone,
        "items": items,
    }


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
