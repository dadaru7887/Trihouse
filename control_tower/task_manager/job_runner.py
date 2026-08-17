"""Advance persisted Jobs through the FMS Gateway, one poll cycle at a time.

`POST /api/v1/orders` creates a Job and its ordered steps, but nothing moves
until two things happen: the Job receives a complete resource assignment, and
its current step is handed to an executor through
`POST /internal/v1/job-steps/{id}/dispatch`.  Before this module existed no
process did either, so every order stopped at `queued` with all steps `pending`
and the RMF outbox empty.  This is that process.

Three properties are deliberate.

**Stateless across cycles.** Which robot, arm, and Packing Dock are busy is
re-derived from the Gateway's own view of active Jobs on every cycle rather than
remembered in this process.  A restart therefore resumes correctly, and this
runner can never disagree with the database about what is reserved.  The Gateway
re-validates every assignment under a row lock and remains the authority; the
selection here only avoids proposing something certain to be rejected.

**Stable idempotency keys.** A step stays `pending` from the moment it is
dispatched until an executor starts it, so a polling runner will inevitably see
the same step again. The dispatch key is derived from the step identity alone,
which makes a repeat dispatch return the original outbox record instead of
raising a conflict or creating a duplicate.

**No automatic retry.** A `failed` or `cancelled` step is reported and left
alone. Retrying needs a policy about what is safe to repeat with a physical
robot mid-warehouse, and inventing one here would hide faults during P0
bring-up rather than surface them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from control_tower.fleet_manager.packing_station import (
    PackingDockCandidate,
    choose_packing_dock,
)
from control_tower.gateway.fms_client import (
    DeviceSummary,
    JobAssignmentRequest,
    JobDetailResponse,
    JobRunnerGatewayClient,
    JobStepDetail,
    StepDispatchRequest,
)

from .assignment import CHARGER_BY_MOBILE


# Jobs the runner may still advance. `held` is excluded on purpose: an emergency
# hold must not be lifted by a background poll, only by the operator review path.
ACTIVE_JOB_STATES = frozenset({"queued", "assigned", "running"})

# Jobs whose resources are still occupied. Identical to ACTIVE_JOB_STATES plus
# `held`, because a held Job keeps its robot and dock while it waits.
OCCUPYING_JOB_STATES = ACTIVE_JOB_STATES | {"held"}

# Only orders created through the public product endpoint are assigned here.
# Internally created jobs (`/internal/v1/jobs`) carry their own assignment.
PUBLIC_ORDER_SOURCE = "public_product_order"

# The canonical `trihouse_test_01` map defines exactly these two reservable
# Packing Docks. They are locations rather than devices, and the Gateway exposes
# no location listing, so the pool is configuration with the canonical default.
DEFAULT_PACKING_DOCK_CODES = ("PACKING-01-DOCK-01", "PACKING-01-DOCK-02")


@dataclass(frozen=True)
class JobRunnerReport:
    """What one poll cycle actually changed, for logging and for tests."""

    assigned: tuple[int, ...] = ()
    dispatched: tuple[int, ...] = ()
    awaiting: tuple[int, ...] = ()
    expired: tuple[int, ...] = ()
    blocked: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.assigned or self.dispatched or self.expired)


@dataclass
class _Cycle:
    """Mutable accumulator for one cycle; frozen into a report at the end."""

    assigned: list[int] = field(default_factory=list)
    dispatched: list[int] = field(default_factory=list)
    awaiting: list[int] = field(default_factory=list)
    expired: list[int] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def report(self) -> JobRunnerReport:
        return JobRunnerReport(
            assigned=tuple(self.assigned),
            dispatched=tuple(self.dispatched),
            awaiting=tuple(self.awaiting),
            expired=tuple(self.expired),
            blocked=tuple(self.blocked),
            errors=tuple(self.errors),
        )


def current_step(steps: tuple[JobStepDetail, ...]) -> JobStepDetail | None:
    """Return the earliest step that has not succeeded yet.

    Ordering is by `step_no` rather than list order so the runner does not
    depend on how the Gateway happened to serialise the steps.
    """
    for step in sorted(steps, key=lambda step: step.step_no):
        if step.state != "succeeded":
            return step
    return None


class JobRunner:
    """Assign resources to queued orders and dispatch their current step."""

    def __init__(
        self,
        gateway: JobRunnerGatewayClient,
        *,
        actor: str = "control-tower-job-runner",
        packing_dock_codes: tuple[str, ...] = DEFAULT_PACKING_DOCK_CODES,
    ) -> None:
        if not packing_dock_codes:
            raise ValueError("at least one Packing Dock code is required")
        self._gateway = gateway
        self._actor = actor
        self._packing_dock_codes = tuple(packing_dock_codes)

    def run_once(self, *, limit: int = 10) -> JobRunnerReport:
        if limit <= 0:
            raise ValueError("limit must be positive")
        cycle = _Cycle()
        self._sweep_expired_reservations(cycle)

        summaries = self._gateway.list_jobs()
        details = self._load_details(summaries, cycle)
        if not details:
            return cycle.report()

        devices = self._gateway.list_devices()
        # Derived from every occupying Job, not only the ones this cycle will
        # touch, so a Job beyond `limit` still holds its resources.
        reserved = _reserved_resources(details)

        for detail in _advanceable(details)[:limit]:
            try:
                self._advance(detail, devices, reserved, cycle)
            except Exception as error:  # noqa: BLE001
                # One job's conflict must not stop the rest of the cycle; the
                # next poll retries it. Recorded so it stays visible in the log.
                cycle.errors.append(f"job {detail.job_id}: {error}")

        return cycle.report()

    def _sweep_expired_reservations(self, cycle: _Cycle) -> None:
        """Hand dead reservations back before deciding what is free.

        순서가 뒤집히면 이 주기의 배정은 이미 죽은 예약이 쥔 자원을 계속 비어 있지
        않다고 읽는다. 그러면 `no free robot` 이 한 주기 더 반복된다.

        회수가 실패해도 주기를 멈추지 않는다 — 이미 배정된 job 은 계속 전진해야
        하고, 다음 주기가 회수를 다시 시도한다.
        """
        sweep = getattr(self._gateway, "expire_reservations", None)
        if sweep is None:
            # 이 경로가 없는 Gateway 를 상대로도 러너는 돌아야 한다.
            return
        try:
            released = sweep().get("expired", ())
        except Exception as error:  # noqa: BLE001
            cycle.errors.append(f"reservation sweep: {error}")
            return
        for entry in released:
            cycle.expired.append(int(entry["reservation_id"]))
            if entry.get("job_active"):
                # 자원은 풀렸는데 로봇이 아직 거기 있을 수 있다. Gateway 가 이미
                # 이상을 열었고, 여기서는 그 사실이 로그에 보이게만 한다.
                cycle.blocked.append(
                    f"job {entry['job_id']}: reservation "
                    f"{entry['reservation_id']} expired while the job still had "
                    "work left"
                )

    def _load_details(
        self,
        summaries: tuple[object, ...],
        cycle: _Cycle,
    ) -> list[JobDetailResponse]:
        details: list[JobDetailResponse] = []
        for summary in summaries:
            state = getattr(summary, "state", "")
            if state not in OCCUPYING_JOB_STATES:
                continue
            job_id = getattr(summary, "job_id")
            try:
                detail = self._gateway.get_job(job_id)
            except Exception as error:  # noqa: BLE001
                cycle.errors.append(f"job {job_id}: {error}")
                continue
            if detail is not None:
                details.append(detail)
        return details

    def _advance(
        self,
        detail: JobDetailResponse,
        devices: tuple[DeviceSummary, ...],
        reserved: "_Reserved",
        cycle: _Cycle,
    ) -> None:
        assignment = detail.context.get("assignment")
        if not assignment:
            if detail.context.get("source") != PUBLIC_ORDER_SOURCE:
                # An internally created job without an assignment is not this
                # runner's to complete; its creator owns that decision.
                cycle.blocked.append(f"job {detail.job_id}: no assignment and not an order")
                return
            request = self._select_assignment(detail, devices, reserved)
            if request is None:
                cycle.blocked.append(f"job {detail.job_id}: no free robot, arm, or dock")
                return
            self._gateway.assign_job_resources(detail.job_id, request)
            reserved.reserve(request)
            cycle.assigned.append(detail.job_id)
            assignment = {"mobile_id": request.mobile_id}

        step = current_step(detail.steps)
        if step is None:
            # Every step succeeded; the Gateway closes the Job on the final
            # outcome, so there is nothing left for the runner to do.
            return
        if step.state == "running":
            cycle.awaiting.append(detail.job_id)
            return
        if step.state != "pending":
            cycle.blocked.append(
                f"job {detail.job_id}: step {step.job_step_id} is {step.state}"
            )
            return

        self._gateway.dispatch_step(
            step.job_step_id,
            StepDispatchRequest(
                idempotency_key=_dispatch_key(detail.job_id, step.job_step_id),
                actor=self._actor,
                assigned_device_id=_step_device(step, assignment),
            ),
        )
        cycle.dispatched.append(detail.job_id)

    def _select_assignment(
        self,
        detail: JobDetailResponse,
        devices: tuple[DeviceSummary, ...],
        reserved: "_Reserved",
    ) -> JobAssignmentRequest | None:
        mobile = _first_free(devices, "mobile", reserved.mobiles)
        arm = _first_free(devices, "arm", reserved.arms)
        if mobile is None or arm is None:
            return None
        charger = CHARGER_BY_MOBILE.get(mobile)
        if charger is None:
            # The Gateway rejects any other pairing with FIXED_CHARGER_MISMATCH,
            # so an unknown robot is a configuration fault, not a retryable one.
            return None
        try:
            dock = choose_packing_dock(
                self._dock_candidates(),
                reserved_codes=frozenset(reserved.docks),
            ).code
        except ValueError:
            return None
        return JobAssignmentRequest(
            revision=1,
            mobile_id=mobile,
            omx_id=arm,
            packing_dock_code=dock,
            charger_code=charger,
        )

    def _dock_candidates(self) -> tuple[PackingDockCandidate, ...]:
        """Build dock candidates with no timing signal available in P0.

        `choose_packing_dock` ranks by reservation availability plus RMF wait
        plus Nav2 travel. None of those are measurable before a route exists, so
        every candidate scores zero and the policy's documented tie-break — the
        Dock code — decides. That keeps selection deterministic and leaves the
        scoring path intact for when real timings can be supplied.
        """
        return tuple(
            PackingDockCandidate(
                code=code,
                reservation_available_at_s=0.0,
                rmf_wait_s=0.0,
                nav2_travel_s=0.0,
            )
            for code in self._packing_dock_codes
        )


@dataclass
class _Reserved:
    mobiles: set[str] = field(default_factory=set)
    arms: set[str] = field(default_factory=set)
    docks: set[str] = field(default_factory=set)

    def reserve(self, request: JobAssignmentRequest) -> None:
        self.mobiles.add(request.mobile_id)
        self.arms.add(request.omx_id)
        self.docks.add(request.packing_dock_code)


def _reserved_resources(details: list[JobDetailResponse]) -> _Reserved:
    reserved = _Reserved()
    for detail in details:
        assignment = detail.context.get("assignment")
        if not isinstance(assignment, dict):
            continue
        for key, target in (
            ("mobile_id", reserved.mobiles),
            ("omx_id", reserved.arms),
            ("packing_dock_code", reserved.docks),
        ):
            value = assignment.get(key)
            if isinstance(value, str) and value:
                target.add(value)
    return reserved


def _advanceable(details: list[JobDetailResponse]) -> list[JobDetailResponse]:
    """Held jobs occupy resources but must not be advanced by a poll."""
    return [detail for detail in details if detail.state in ACTIVE_JOB_STATES]


def _first_free(
    devices: tuple[DeviceSummary, ...],
    device_type: str,
    reserved: set[str],
) -> str | None:
    candidates = sorted(
        device.device_id
        for device in devices
        if device.device_type == device_type
        and device.assignable
        and device.device_id not in reserved
    )
    return candidates[0] if candidates else None


def _step_device(step: JobStepDetail, assignment: object) -> str | None:
    """Name the mobile executor so the Gateway can reject a mismatched robot.

    Arm and worker steps are left unnamed: the Gateway resolves those from the
    Job's own assignment, and sending a robot ID for them would be rejected as
    a device mismatch.
    """
    if step.assigned_device_id is not None:
        return step.assigned_device_id
    if step.executor_type != "mobile":
        return None
    if isinstance(assignment, dict):
        mobile = assignment.get("mobile_id")
        if isinstance(mobile, str) and mobile:
            return mobile
    return None


def _dispatch_key(job_id: int, job_step_id: int) -> str:
    """Derive the key from step identity so a repeated poll is a no-op.

    The Gateway returns the original outbox record when the key and the request
    fingerprint both match, which is exactly what a re-poll of a still-pending
    step should produce.
    """
    return f"control-tower-runner-job-{job_id}-step-{job_step_id}"


__all__ = [
    "ACTIVE_JOB_STATES",
    "DEFAULT_PACKING_DOCK_CODES",
    "JobRunner",
    "JobRunnerReport",
    "current_step",
]
