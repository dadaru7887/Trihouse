"""TaskOrchestrator physical zone-handover runtime contract tests."""

from dataclasses import replace

from control_tower.task_manager.execution_result import (
    ActorRole,
    AttemptOutcome,
    CompletionEvent,
    ExecutionFact,
)
from control_tower.task_manager.execution_store import InMemoryExecutionStore
from control_tower.task_manager.stage_engine import StageEngine, StageState
from control_tower.task_manager.task_orchestrator import StageSpec, TaskOrchestrator
from control_tower.task_manager.zone_handover import ReadinessFact, ReadinessRole


def _specs() -> tuple[StageSpec, ...]:
    return (
        StageSpec(
            stage_id="READY_TO_LOAD",
            required_roles=frozenset({ActorRole.PINKY, ActorRole.OMX}),
            handover_group_id="group-ambient",
        ),
        StageSpec(
            stage_id="LOAD",
            required_roles=frozenset({ActorRole.OMX}),
            command_kind="START_LOAD",
            target_role=ActorRole.OMX,
            method_code="OMX_LOAD",
        ),
    )


def _runtime(*, store=None, stages=None) -> tuple[TaskOrchestrator, InMemoryExecutionStore, StageEngine]:
    actual_store = store or InMemoryExecutionStore()
    actual_stages = stages or StageEngine()
    runtime = TaskOrchestrator(store=actual_store, stages=actual_stages)
    runtime.create("job-1", stages=_specs())
    runtime.assign(
        "job-1",
        assignment_revision=4,
        actors={ActorRole.PINKY: "PK_01", ActorRole.OMX: "OMX_01"},
    )
    runtime.start("job-1", safety_approved=True)
    return runtime, actual_store, actual_stages


def _pinky(fact_id: str = "p-1") -> ReadinessFact:
    return ReadinessFact(
        fact_id=fact_id,
        job_id="job-1",
        handover_group_id="group-ambient",
        assignment_revision=4,
        role=ReadinessRole.PINKY,
        device_id="PK_01",
        dock_arrived=True,
        stationary=True,
        current_assignment=True,
    )


def _omx(fact_id: str = "o-1") -> ReadinessFact:
    return ReadinessFact(
        fact_id=fact_id,
        job_id="job-1",
        handover_group_id="group-ambient",
        assignment_revision=4,
        role=ReadinessRole.OMX,
        device_id="OMX_01",
        expected_item=True,
        safe_handover_pose=True,
    )


def test_runtime_releases_exactly_one_start_load_in_either_arrival_order() -> None:
    for first, second in ((_pinky(), _omx()), (_omx(), _pinky())):
        runtime, store, _ = _runtime()
        waiting = runtime.record_readiness(first, safety_approved=True)
        released = runtime.record_readiness(second, safety_approved=True)
        replay = runtime.record_readiness(
            replace(second, fact_id=f"{second.fact_id}-replay"), safety_approved=True
        )

        assert waiting.commands == ()
        assert [command.command_kind for command in released.commands] == ["START_LOAD"]
        assert replay.commands == ()
        assert len(store.commands) == 1


def test_runtime_rejects_wrong_identity_and_missing_physical_criteria() -> None:
    runtime, _, _ = _runtime()
    runtime.record_readiness(_pinky(), safety_approved=True)
    rejected = (
        replace(_omx("cross-job"), job_id="job-2"),
        replace(_omx("cross-group"), handover_group_id="group-frozen"),
        replace(_omx("stale"), assignment_revision=3),
        replace(_omx("device"), device_id="OMX_02"),
        replace(_omx("pose"), safe_handover_pose=False),
        replace(_pinky("moving"), stationary=False),
    )

    assert all(
        not runtime.record_readiness(fact, safety_approved=True).accepted
        for fact in rejected
    )
    assert runtime.stage_state("job-1", "READY_TO_LOAD") is StageState.RUNNING


def test_generic_boolean_completion_cannot_open_physical_gate() -> None:
    runtime, store, _ = _runtime()
    event = CompletionEvent("legacy", "job-1", "READY_TO_LOAD", 4, ActorRole.PINKY, "PK_01", True)
    fact = ExecutionFact(
        event_id="legacy",
        job_id="job-1",
        job_step_id="READY_TO_LOAD",
        assignment_revision=4,
        actor_role=ActorRole.PINKY,
        actor_id="PK_01",
        command_uuid="legacy-command",
        method_code="ARRIVED",
        command_outcome=AttemptOutcome.SUCCEEDED,
    )

    result = runtime.record_completion(event, fact, safety_approved=True)

    assert result.accepted is False
    assert result.reason_code == "READINESS_FACT_REQUIRED"
    assert store.executions == []


def test_restart_recovers_one_sided_readiness_and_replay_fence() -> None:
    runtime, store, stages = _runtime()
    runtime.record_readiness(_pinky(), safety_approved=True)

    restarted = TaskOrchestrator(store=store, stages=stages)
    restarted.recover(
        "job-1",
        stages=_specs(),
        assignment_revision=4,
        actors={ActorRole.PINKY: "PK_01", ActorRole.OMX: "OMX_01"},
    )
    duplicate = restarted.record_readiness(_pinky(), safety_approved=True)
    released = restarted.record_readiness(_omx(), safety_approved=True)

    assert duplicate.duplicate is True
    assert [command.command_kind for command in released.commands] == ["START_LOAD"]
    assert len(store.commands) == 1


def test_explicit_reassignment_discards_old_readiness() -> None:
    runtime, _, _ = _runtime()
    runtime.record_readiness(_pinky(), safety_approved=True)
    reassigned = runtime.reassign_pinky("job-1", assignment_revision=5, pinky_id="PK_02")
    stale = runtime.record_readiness(_omx(), safety_approved=True)
    new_omx = replace(_omx("new-o"), assignment_revision=5)
    new_pinky = replace(_pinky("new-p"), assignment_revision=5, device_id="PK_02")

    assert reassigned.accepted is True
    assert stale.reason_code == "STALE_ASSIGNMENT"
    assert runtime.record_readiness(new_omx, safety_approved=True).commands == ()
    assert [c.command_kind for c in runtime.record_readiness(new_pinky, safety_approved=True).commands] == ["START_LOAD"]
