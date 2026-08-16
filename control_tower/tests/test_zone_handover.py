"""Same-assignment readiness and item load-result tests."""

from dataclasses import replace

import pytest

from control_tower.task_manager.zone_handover import (
    ItemLoadAttempt,
    ReadinessFact,
    ReadinessRole,
    ZoneHandover,
)


def _handover() -> ZoneHandover:
    return ZoneHandover(
        job_id="job-1",
        handover_group_id="group-ambient",
        assignment_revision=4,
        pinky_id="PK_01",
        omx_id="OMX_01",
    )


def _pinky_ready() -> ReadinessFact:
    return ReadinessFact(
        fact_id="pinky-ready-1",
        job_id="job-1",
        handover_group_id="group-ambient",
        assignment_revision=4,
        role=ReadinessRole.PINKY,
        device_id="PK_01",
        dock_arrived=True,
        stationary=True,
        current_assignment=True,
    )


def _omx_ready() -> ReadinessFact:
    return ReadinessFact(
        fact_id="omx-ready-1",
        job_id="job-1",
        handover_group_id="group-ambient",
        assignment_revision=4,
        role=ReadinessRole.OMX,
        device_id="OMX_01",
        expected_item=True,
        safe_handover_pose=True,
    )


@pytest.mark.parametrize("first", [ReadinessRole.PINKY, ReadinessRole.OMX])
def test_loading_waits_for_both_same_assignment_then_releases_once(first) -> None:
    """Either arrival order converges to exactly one START_LOAD command."""
    handover = _handover()
    first_fact, second_fact = (
        (_pinky_ready(), _omx_ready())
        if first is ReadinessRole.PINKY
        else (_omx_ready(), _pinky_ready())
    )

    waiting = handover.record(first_fact)
    released = handover.record(second_fact)
    replay = handover.record(replace(second_fact, fact_id="peer-ready-replay"))

    assert waiting.released is False
    assert waiting.reason_code == "WAITING_FOR_PEER"
    assert released.released is True
    assert released.command == "START_LOAD"
    assert replay.released is False
    assert replay.reason_code == "ALREADY_RELEASED"


@pytest.mark.parametrize(
    ("fact", "reason"),
    [
        (replace(_omx_ready(), job_id="job-2"), "CROSS_JOB_FACT"),
        (replace(_omx_ready(), handover_group_id="group-frozen"), "UNEXPECTED_GROUP"),
        (replace(_omx_ready(), assignment_revision=3), "STALE_ASSIGNMENT"),
        (replace(_omx_ready(), device_id="OMX_02"), "UNEXPECTED_DEVICE"),
    ],
)
def test_stale_cross_job_cross_group_and_cross_device_facts_never_count(
    fact: ReadinessFact, reason: str
) -> None:
    """Only all fields of the current immutable assignment can open the gate."""
    handover = _handover()
    handover.record(_pinky_ready())

    rejected = handover.record(fact)

    assert rejected.accepted is False
    assert rejected.released is False
    assert rejected.reason_code == reason


def test_readiness_requires_physical_role_specific_criteria() -> None:
    """Identity alone is insufficient without stationary Dock/safe-pose evidence."""
    handover = _handover()

    pinky = handover.record(replace(_pinky_ready(), stationary=False))
    omx = handover.record(replace(_omx_ready(), safe_handover_pose=False))

    assert pinky.reason_code == "PINKY_NOT_READY"
    assert omx.reason_code == "OMX_NOT_READY"


def _attempt(result: str) -> ItemLoadAttempt:
    return ItemLoadAttempt(
        attempt_id=f"attempt-{result}",
        item_id="item-1",
        result=result,
        criteria={"expected_item": True, "safe_pose": True},
        observations={"qr": "SKU-MANDARIN", "gripper": "open"},
        metrics={"pose_error_m": {"value": 0.004, "unit": "m"}},
        evidence_refs=("recording://cam-1/segment-7",),
        policy_name="p0-load-contract",
        policy_version="1",
        model_name="fixture-observer",
        model_version="1",
    )


@pytest.mark.parametrize(
    ("result", "departure_allowed"),
    [
        ("LOAD_CONFIRMED", True),
        ("DROP_DETECTED", False),
        ("LOAD_UNCERTAIN", False),
        ("GRASP_RETAINED", False),
    ],
)
def test_only_load_confirmed_allows_pinky_departure(
    result: str, departure_allowed: bool
) -> None:
    """Every terminal fixture is persisted, but only confirmed cargo can depart."""
    handover = _handover()

    state = handover.record_load_attempt(_attempt(result))

    assert state.pinky_departure_allowed is departure_allowed
    assert handover.attempts == (_attempt(result),)


def test_attempt_records_require_training_lineage_and_evidence_fields() -> None:
    """Incomplete observations cannot become future VLM/RL training records."""
    handover = _handover()

    with pytest.raises(ValueError, match="attempt record"):
        handover.record_load_attempt(replace(_attempt("LOAD_UNCERTAIN"), criteria={}))
