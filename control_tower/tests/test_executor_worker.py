"""Contract tests for the worker that closes OMX and FMS steps."""

import pytest

from control_tower.gateway.fms_client import (
    ExecutorDispatch,
    StepOutcomeResponse,
)
from control_tower.task_manager.executor_worker import (
    EXECUTOR_CHANNELS,
    ExecutorWorker,
)


def _dispatch(
    job_step_id=100,
    *,
    action_type="pick",
    executor_type="arm",
    channel="omx",
    device="OMX_01",
    revision=1,
    payload=None,
):
    return ExecutorDispatch(
        message_id=f"message-{job_step_id}",
        job_id=7,
        job_step_id=job_step_id,
        channel=channel,
        message_type="execute_action",
        action_type=action_type,
        executor_type=executor_type,
        payload=payload if payload is not None else {"input": {"sku": "SKU-1"}},
        assigned_device_id=device,
        assignment_revision=revision,
        assignment={"omx_id": "OMX_01", "mobile_id": "PK_01"},
    )


class FakeSimulator:
    def __init__(self, omx_id="OMX_01", fail_with=None):
        self._omx_id = omx_id
        self.commands = []
        self._fail_with = fail_with

    @property
    def state(self):
        return "OMX_READY"

    def execute(self, command):
        if self._fail_with is not None:
            raise self._fail_with
        self.commands.append(command)
        return ()


class FakeGateway:
    def __init__(self, dispatches, fail_outcome_with=None):
        self._dispatches = tuple(dispatches)
        self.claims = []
        self.outcomes = []
        self.fail_outcome_with = fail_outcome_with

    def claim_executor_dispatches(self, request):
        self.claims.append(request)
        return self._dispatches

    def record_executor_outcome(self, job_step_id, request, *, idempotency_key):
        if self.fail_outcome_with is not None:
            raise self.fail_outcome_with
        self.outcomes.append((job_step_id, request, idempotency_key))
        return StepOutcomeResponse(
            job_step_id=job_step_id,
            job_id=7,
            state="succeeded" if request.outcome == "succeeded" else "failed",
            attempt_uuid="attempt-1",
            attempt_no=1,
        )


def _worker(gateway, simulators=None, **kwargs):
    return ExecutorWorker(
        gateway,
        simulators=simulators if simulators is not None else {"OMX_01": FakeSimulator()},
        **kwargs,
    )


def test_a_pick_is_executed_by_the_arm_and_then_closed() -> None:
    """The gap this worker closes: an arm step could never leave `pending`."""
    simulator = FakeSimulator()
    gateway = FakeGateway([_dispatch()])

    report = _worker(gateway, {"OMX_01": simulator}).run_once()

    assert report.succeeded == (100,)
    assert len(simulator.commands) == 1
    assert simulator.commands[0]["kind"] == "prepare"
    assert simulator.commands[0]["omx_id"] == "OMX_01"
    _, request, _ = gateway.outcomes[0]
    assert request.outcome == "succeeded"
    assert request.assignment_revision == 1


def test_the_worker_claims_only_its_own_channels() -> None:
    """`rmf` belongs to the RMF worker; claiming it would steal navigation."""
    gateway = FakeGateway([])

    _worker(gateway).run_once()

    assert gateway.claims[0].channels == EXECUTOR_CHANNELS
    assert "rmf" not in gateway.claims[0].channels


def test_a_wait_step_is_left_for_the_packing_worker() -> None:
    """A background process must never sign off work a human confirms."""
    gateway = FakeGateway(
        [_dispatch(action_type="wait", executor_type="fms", channel="pinky", device=None)]
    )

    report = _worker(gateway).run_once()

    assert gateway.outcomes == []
    assert report.succeeded == ()
    assert any("awaits the worker" in item for item in report.deferred)


def test_an_fms_step_is_closed_without_an_arm() -> None:
    gateway = FakeGateway(
        [_dispatch(action_type="handover", executor_type="fms", channel="pinky", device=None)]
    )

    report = _worker(gateway).run_once()

    assert report.succeeded == (100,)
    _, request, _ = gateway.outcomes[0]
    assert request.method_code == "FMS_SIMULATED_CONTRACT"
    assert request.actor_device_id is None


def test_the_outcome_key_is_stable_for_the_same_step_and_revision() -> None:
    """A retry after a lost response must not close the step twice."""
    gateway = FakeGateway([_dispatch()])
    worker = _worker(gateway)

    worker.run_once()
    worker.run_once()

    keys = {key for _, _, key in gateway.outcomes}
    assert len(gateway.outcomes) == 2
    assert len(keys) == 1


def test_a_new_assignment_revision_gets_a_new_key() -> None:
    """A reassigned step is different work and deserves its own attempt."""
    gateway = FakeGateway([_dispatch(revision=1), _dispatch(revision=2)])

    _worker(gateway).run_once()

    keys = {key for _, _, key in gateway.outcomes}
    assert len(keys) == 2


def test_every_sample_carries_its_environment() -> None:
    """Simulated runs must never calibrate the hardware duration model."""
    gateway = FakeGateway([_dispatch()])

    _worker(gateway, environment="simulation").run_once()

    _, request, _ = gateway.outcomes[0]
    assert request.metrics["duration"]["environment"] == "simulation"


def test_a_pick_records_its_grasp_segment() -> None:
    """Decomposed time is what the duration baseline is built from."""
    # total 은 바깥에서, grasp 는 팔 실행 구간에서 각각 두 번 읽는다.
    ticks = iter((1_000, 1_020, 1_050, 1_080))
    gateway = FakeGateway([_dispatch()])

    _worker(gateway, clock_ms=lambda: next(ticks)).run_once()

    duration = gateway.outcomes[0][1].metrics["duration"]
    assert duration["segments"]["grasp_ms"] == 30
    assert duration["total_ms"] == 80


def test_a_missing_simulator_is_reported_not_silently_succeeded() -> None:
    """Reporting success for an arm that never ran would corrupt the samples."""
    gateway = FakeGateway([_dispatch(device="OMX_09")])

    report = _worker(gateway).run_once()

    assert gateway.outcomes == []
    assert any("step 100" in error for error in report.errors)


def test_one_failing_dispatch_does_not_stop_the_cycle() -> None:
    gateway = FakeGateway([_dispatch(101, device="OMX_09"), _dispatch(102)])

    report = _worker(gateway).run_once()

    assert report.succeeded == (102,)
    assert len(report.errors) == 1


def test_an_arm_falls_back_to_the_job_assignment_for_its_identity() -> None:
    simulator = FakeSimulator()
    gateway = FakeGateway([_dispatch(device=None)])

    _worker(gateway, {"OMX_01": simulator}).run_once()

    assert simulator.commands[0]["omx_id"] == "OMX_01"


def test_expected_items_come_from_the_step_input() -> None:
    simulator = FakeSimulator()
    gateway = FakeGateway(
        [_dispatch(payload={"input": {"expected_items": ["SKU-A", "SKU-B"]}})]
    )

    _worker(gateway, {"OMX_01": simulator}).run_once()

    assert simulator.commands[0]["expected_items"] == ("SKU-A", "SKU-B")


def test_a_non_positive_limit_is_rejected() -> None:
    with pytest.raises(ValueError):
        _worker(FakeGateway([])).run_once(limit=0)
