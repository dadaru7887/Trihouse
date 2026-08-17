"""Contract tests for the runner that advances queued Jobs into dispatches."""

import pytest

from control_tower.gateway.fms_client import (
    DeviceSummary,
    JobAssignmentResponse,
    JobDetailResponse,
    JobStepDetail,
    JobSummary,
    StepDispatchResponse,
)
from control_tower.task_manager.job_runner import (
    DEFAULT_PACKING_DOCK_CODES,
    JobRunner,
    current_step,
)


def _devices(*, mobiles=("PK_01", "PK_02"), arms=("OMX_01", "OMX_02"), health="ok"):
    return tuple(
        DeviceSummary(
            device_id=device_id,
            device_type=device_type,
            control_mode="automatic",
            state="idle",
            health=health,
        )
        for device_type, group in (("mobile", mobiles), ("arm", arms))
        for device_id in group
    )


def _steps(*states: str, executor_type: str = "mobile"):
    return tuple(
        JobStepDetail(
            job_step_id=100 + index,
            step_no=index + 1,
            action_type="navigate",
            executor_type=executor_type,
            state=state,
        )
        for index, state in enumerate(states)
    )


def _order_job(job_id: int, *, state="queued", assignment=None, steps=None):
    context = {"source": "public_product_order"}
    if assignment is not None:
        context["assignment"] = assignment
    return JobDetailResponse(
        job_id=job_id,
        job_code=f"JOB-{job_id}",
        state=state,
        context=context,
        steps=steps if steps is not None else _steps("pending", "pending"),
    )


def _assignment(mobile: str, omx: str, dock: str, charger: str) -> dict:
    return {
        "revision": 1,
        "mobile_id": mobile,
        "omx_id": omx,
        "packing_dock_code": dock,
        "charger_code": charger,
    }


class FakeGateway:
    """In-memory stand-in that records the calls the runner makes."""

    def __init__(self, details, devices=None):
        self._details = {detail.job_id: detail for detail in details}
        self._devices = devices if devices is not None else _devices()
        self.assignments = []
        self.dispatches = []
        self.fail_assignment_with = None

    def list_jobs(self):
        return tuple(
            JobSummary(job_id=detail.job_id, job_code=detail.job_code, state=detail.state)
            for detail in self._details.values()
        )

    def get_job(self, job_id):
        return self._details.get(job_id)

    def list_devices(self):
        return self._devices

    def assign_job_resources(self, job_id, request):
        if self.fail_assignment_with is not None:
            raise self.fail_assignment_with
        self.assignments.append((job_id, request))
        detail = self._details[job_id]
        self._details[job_id] = JobDetailResponse(
            job_id=detail.job_id,
            job_code=detail.job_code,
            state=detail.state,
            context={
                **detail.context,
                "assignment": _assignment(
                    request.mobile_id,
                    request.omx_id,
                    request.packing_dock_code,
                    request.charger_code,
                ),
            },
            steps=detail.steps,
        )
        return JobAssignmentResponse(job_id=job_id, **vars(request))

    def dispatch_step(self, job_step_id, request):
        self.dispatches.append((job_step_id, request))
        return StepDispatchResponse(
            message_id=f"message-{job_step_id}",
            idempotency_key=request.idempotency_key,
            job_id=0,
            job_step_id=job_step_id,
            channel="rmf",
            message_type="navigate",
            state="pending",
            payload={},
        )


def test_queued_order_receives_an_assignment_and_its_first_dispatch() -> None:
    """The gap this runner closes: a queued order must reach the RMF outbox."""
    gateway = FakeGateway([_order_job(1)])

    report = JobRunner(gateway).run_once()

    assert report.assigned == (1,)
    assert report.dispatched == (1,)
    assigned_job, request = gateway.assignments[0]
    assert assigned_job == 1
    assert request.revision == 1
    assert request.mobile_id == "PK_01"
    assert request.omx_id == "OMX_01"
    assert request.charger_code == "TRIHOUSE-TEST-01-CHG-01"
    assert request.packing_dock_code == DEFAULT_PACKING_DOCK_CODES[0]
    # The first step, not an arbitrary one.
    assert gateway.dispatches[0][0] == 100


def test_two_concurrent_orders_take_different_robots_arms_and_docks() -> None:
    """Two Pinky operation depends on the runner never double-booking."""
    gateway = FakeGateway([_order_job(1), _order_job(2)])

    report = JobRunner(gateway).run_once()

    assert report.assigned == (1, 2)
    requests = [request for _, request in gateway.assignments]
    assert {request.mobile_id for request in requests} == {"PK_01", "PK_02"}
    assert {request.omx_id for request in requests} == {"OMX_01", "OMX_02"}
    assert len({request.packing_dock_code for request in requests}) == 2
    assert {request.mobile_id: request.charger_code for request in requests} == {
        "PK_01": "TRIHOUSE-TEST-01-CHG-01",
        "PK_02": "TRIHOUSE-TEST-01-CHG-02",
    }


def test_a_third_order_waits_because_no_robot_is_free() -> None:
    """Exhausted resources must block, not raise and not steal a busy robot."""
    gateway = FakeGateway([_order_job(1), _order_job(2), _order_job(3)])

    report = JobRunner(gateway).run_once()

    assert report.assigned == (1, 2)
    assert any("job 3" in blocked for blocked in report.blocked)
    assert len(gateway.assignments) == 2


def test_resources_held_by_an_existing_job_are_not_reassigned() -> None:
    """Reservations are re-derived from the Gateway, so a restart is safe."""
    running = _order_job(
        1,
        state="running",
        assignment=_assignment(
            "PK_01", "OMX_01", "PACKING-01-DOCK-01", "TRIHOUSE-TEST-01-CHG-01"
        ),
        steps=_steps("succeeded", "running"),
    )
    gateway = FakeGateway([running, _order_job(2)])

    JobRunner(gateway).run_once()

    _, request = gateway.assignments[0]
    assert request.mobile_id == "PK_02"
    assert request.omx_id == "OMX_02"
    assert request.packing_dock_code == "PACKING-01-DOCK-02"


def test_a_held_job_keeps_its_resources_but_is_never_advanced() -> None:
    """An emergency hold must be released by operator review, not by a poll."""
    held = _order_job(
        1,
        state="held",
        assignment=_assignment(
            "PK_01", "OMX_01", "PACKING-01-DOCK-01", "TRIHOUSE-TEST-01-CHG-01"
        ),
        steps=_steps("succeeded", "pending"),
    )
    gateway = FakeGateway([held])

    report = JobRunner(gateway).run_once()

    assert gateway.dispatches == []
    assert report.dispatched == ()


def test_a_running_step_is_awaited_rather_than_dispatched_again() -> None:
    """Only a pending step is dispatchable; in-flight work must be left alone."""
    job = _order_job(
        1,
        state="running",
        assignment=_assignment(
            "PK_01", "OMX_01", "PACKING-01-DOCK-01", "TRIHOUSE-TEST-01-CHG-01"
        ),
        steps=_steps("succeeded", "running", "pending"),
    )
    gateway = FakeGateway([job])

    report = JobRunner(gateway).run_once()

    assert gateway.dispatches == []
    assert report.awaiting == (1,)


def test_the_next_step_is_dispatched_once_the_previous_one_succeeded() -> None:
    """Sequencing: success on step N unlocks exactly step N+1."""
    job = _order_job(
        1,
        state="running",
        assignment=_assignment(
            "PK_01", "OMX_01", "PACKING-01-DOCK-01", "TRIHOUSE-TEST-01-CHG-01"
        ),
        steps=_steps("succeeded", "pending", "pending"),
    )
    gateway = FakeGateway([job])

    JobRunner(gateway).run_once()

    assert [step_id for step_id, _ in gateway.dispatches] == [101]


def test_repeating_a_cycle_reuses_the_same_idempotency_key() -> None:
    """A still-pending step is re-seen every poll; that must not duplicate work."""
    gateway = FakeGateway([_order_job(1)])
    runner = JobRunner(gateway)

    runner.run_once()
    runner.run_once()

    keys = {request.idempotency_key for _, request in gateway.dispatches}
    assert len(gateway.dispatches) == 2
    assert len(keys) == 1


def test_a_failed_step_is_reported_and_never_retried_automatically() -> None:
    """Retrying physical work needs a policy; silence would hide the fault."""
    job = _order_job(
        1,
        state="running",
        assignment=_assignment(
            "PK_01", "OMX_01", "PACKING-01-DOCK-01", "TRIHOUSE-TEST-01-CHG-01"
        ),
        steps=_steps("succeeded", "failed", "pending"),
    )
    gateway = FakeGateway([job])

    report = JobRunner(gateway).run_once()

    assert gateway.dispatches == []
    assert any("is failed" in blocked for blocked in report.blocked)


def test_an_unavailable_device_is_not_proposed() -> None:
    """Proposing a faulted robot would only earn a Gateway rejection."""
    devices = _devices(mobiles=("PK_01",), arms=("OMX_01",), health="fault")
    gateway = FakeGateway([_order_job(1)], devices=devices)

    report = JobRunner(gateway).run_once()

    assert gateway.assignments == []
    assert report.blocked


def test_a_mobile_step_carries_the_assigned_robot_identity() -> None:
    """The Gateway rejects a mismatched robot, so the runner must name the right one."""
    gateway = FakeGateway([_order_job(1)])

    JobRunner(gateway).run_once()

    _, request = gateway.dispatches[0]
    assert request.assigned_device_id == "PK_01"


def test_a_non_mobile_step_is_dispatched_without_a_robot_identity() -> None:
    """Arm and worker steps resolve their executor from the job assignment."""
    job = _order_job(
        1,
        state="running",
        assignment=_assignment(
            "PK_01", "OMX_01", "PACKING-01-DOCK-01", "TRIHOUSE-TEST-01-CHG-01"
        ),
        steps=_steps("pending", executor_type="arm"),
    )
    gateway = FakeGateway([job])

    JobRunner(gateway).run_once()

    _, request = gateway.dispatches[0]
    assert request.assigned_device_id is None


def test_one_job_failing_does_not_stop_the_rest_of_the_cycle() -> None:
    """A polling daemon must survive a single conflicting job."""
    gateway = FakeGateway([_order_job(1)])
    gateway.fail_assignment_with = RuntimeError("HTTP 409 RESOURCE_UNAVAILABLE")

    report = JobRunner(gateway).run_once()

    assert report.assigned == ()
    assert any("job 1" in error for error in report.errors)


def test_a_completed_job_frees_its_resources_for_the_next_order() -> None:
    """Completion is not an occupying state, so PK_01 becomes assignable again."""
    completed = JobDetailResponse(
        job_id=1,
        job_code="JOB-1",
        state="completed",
        context={
            "source": "public_product_order",
            "assignment": _assignment(
                "PK_01", "OMX_01", "PACKING-01-DOCK-01", "TRIHOUSE-TEST-01-CHG-01"
            ),
        },
        steps=_steps("succeeded"),
    )
    gateway = FakeGateway([completed, _order_job(2)])

    JobRunner(gateway).run_once()

    _, request = gateway.assignments[0]
    assert request.mobile_id == "PK_01"


def test_an_internally_created_job_is_left_to_its_own_creator() -> None:
    """Only public product orders are assigned here."""
    internal = JobDetailResponse(
        job_id=1,
        job_code="JOB-1",
        state="queued",
        context={},
        steps=_steps("pending"),
    )
    gateway = FakeGateway([internal])

    report = JobRunner(gateway).run_once()

    assert gateway.assignments == []
    assert any("not an order" in blocked for blocked in report.blocked)


def test_limit_bounds_the_jobs_advanced_in_one_cycle() -> None:
    gateway = FakeGateway([_order_job(1), _order_job(2)])

    report = JobRunner(gateway).run_once(limit=1)

    assert len(report.assigned) == 1


def test_a_non_positive_limit_is_rejected() -> None:
    with pytest.raises(ValueError):
        JobRunner(FakeGateway([])).run_once(limit=0)


def test_current_step_orders_by_step_number_not_list_order() -> None:
    """The runner must not depend on the Gateway's serialisation order."""
    steps = _steps("pending", "succeeded")
    reversed_steps = tuple(reversed(steps))

    assert current_step(reversed_steps).step_no == 1


def test_current_step_is_none_when_every_step_succeeded() -> None:
    assert current_step(_steps("succeeded", "succeeded")) is None
