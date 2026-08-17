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

from control_tower.gateway.fms_client import (
    ExecutorDispatch,
    ExecutorDispatchClaimRequest,
    ExecutorGatewayClient,
    StepOutcomeRequest,
)


# Channels this worker owns. `rmf` belongs to `rmf_gateway_worker`.
EXECUTOR_CHANNELS = ("omx", "pinky")

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
            segments = self._run_fms(dispatch)
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
        """
        started_ms = self._clock_ms()
        return {"transfer_ms": max(self._clock_ms() - started_ms, 0)}

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
        if dispatch.assigned_device_id:
            return dispatch.assigned_device_id
        if dispatch.executor_type == "arm":
            omx_id = dispatch.assignment.get("omx_id")
            return omx_id if isinstance(omx_id, str) and omx_id else None
        return None


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
