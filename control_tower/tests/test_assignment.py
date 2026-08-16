"""Control Tower resource assignment policy tests."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from control_tower.task_manager.assignment import (
    AssignmentConflict,
    ControlTowerAssigner,
    DeviceCandidate,
    PackingDockCandidate,
)


def _mobiles() -> tuple[DeviceCandidate, ...]:
    return (
        DeviceCandidate("PK_02", available=True),
        DeviceCandidate("PK_01", available=True),
    )


def _arms() -> tuple[DeviceCandidate, ...]:
    return (
        DeviceCandidate("OMX_02", available=True),
        DeviceCandidate("OMX_01", available=True),
    )


def _packing_docks() -> tuple[PackingDockCandidate, ...]:
    return (
        PackingDockCandidate(
            "PACKING-01-DOCK-01",
            reservation_available_at_s=15.0,
            rmf_wait_s=2.0,
            nav2_travel_s=4.0,
        ),
        PackingDockCandidate(
            "PACKING-01-DOCK-02",
            reservation_available_at_s=4.0,
            rmf_wait_s=3.0,
            nav2_travel_s=5.0,
        ),
    )


def test_control_tower_assigns_every_resource_once() -> None:
    """A queued job receives one deterministic, complete immutable assignment."""
    assignment = ControlTowerAssigner().assign(
        "job-1",
        revision=1,
        mobiles=_mobiles(),
        arms=_arms(),
        packing_docks=_packing_docks(),
    )

    assert assignment.mobile_id == "PK_01"
    assert assignment.omx_id == "OMX_01"
    assert assignment.packing_dock_code == "PACKING-01-DOCK-02"
    assert assignment.charger_code == "TRIHOUSE-TEST-01-CHG-01"
    assert assignment.revision == 1


def test_packing_score_ties_break_by_canonical_code() -> None:
    """Input ordering cannot make equal-cost packing selection nondeterministic."""
    candidates = (
        PackingDockCandidate("PACKING-01-DOCK-02", 4.0, 3.0, 5.0),
        PackingDockCandidate("PACKING-01-DOCK-01", 6.0, 1.0, 5.0),
    )

    assignment = ControlTowerAssigner().assign(
        "job-1", revision=1, mobiles=_mobiles(), arms=_arms(), packing_docks=candidates
    )

    assert assignment.packing_dock_code == "PACKING-01-DOCK-01"


def test_unavailable_and_reserved_resources_are_never_double_assigned() -> None:
    """Concurrent decisions cannot reserve the same device or Dock twice."""
    assigner = ControlTowerAssigner()

    def assign(job_id: str):
        return assigner.assign(
            job_id,
            revision=1,
            mobiles=_mobiles(),
            arms=_arms(),
            packing_docks=_packing_docks(),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(assign, ("job-1", "job-2")))

    assert {result.mobile_id for result in results} == {"PK_01", "PK_02"}
    assert {result.omx_id for result in results} == {"OMX_01", "OMX_02"}
    assert {result.packing_dock_code for result in results} == {
        "PACKING-01-DOCK-01",
        "PACKING-01-DOCK-02",
    }


def test_same_job_revision_replays_but_changed_identity_requires_new_revision() -> None:
    """An assignment revision is immutable after its first successful selection."""
    assigner = ControlTowerAssigner()
    first = assigner.assign(
        "job-1", revision=4, mobiles=_mobiles(), arms=_arms(), packing_docks=_packing_docks()
    )

    replay = assigner.assign(
        "job-1", revision=4, mobiles=_mobiles(), arms=_arms(), packing_docks=_packing_docks()
    )
    assert replay == first

    with pytest.raises(AssignmentConflict):
        assigner.reassign(
            "job-1",
            revision=4,
            mobiles=_mobiles(),
            arms=_arms(),
            packing_docks=_packing_docks(),
        )


def test_rmf_cannot_silently_substitute_the_assigned_pinky() -> None:
    """Traffic coordination cannot change Control Tower's device identity."""
    assigner = ControlTowerAssigner()
    assignment = assigner.assign(
        "job-1", revision=4, mobiles=_mobiles(), arms=_arms(), packing_docks=_packing_docks()
    )

    rejected = assigner.validate_rmf_acceptance(
        "job-1", revision=4, assigned_mobile_id="PK_02"
    )
    accepted = assigner.validate_rmf_acceptance(
        "job-1", revision=4, assigned_mobile_id=assignment.mobile_id
    )

    assert rejected.accepted is False
    assert rejected.reason_code == "ASSIGNMENT_DEVICE_MISMATCH"
    assert accepted.accepted is True
