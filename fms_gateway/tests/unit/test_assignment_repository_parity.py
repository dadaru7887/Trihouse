"""In-memory assignment transaction parity and location validation."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from fms_gateway.app.repositories import (
    InMemoryFmsRepository,
    ResourceAssignmentConflict,
    ResourceUnavailable,
)


ASSIGNMENT = {
    "revision": 1,
    "mobile_id": "PK_01",
    "omx_id": "OMX_01",
    "packing_dock_code": "PACKING-01-DOCK-01",
    "charger_code": "TRIHOUSE-TEST-01-CHG-01",
}


def _job(repository: InMemoryFmsRepository, code: str) -> int:
    return repository.create_job(
        {
            "job_code": code,
            "operation_type": "outbound",
            "priority": "normal",
            "context": {"source": "public_product_order"},
            "steps": [
                {
                    "step_no": 10,
                    "action_type": "wait",
                    "executor_type": "fms",
                    "target_location_id": 99,
                    "input": {"wait_for": "worker_completion"},
                }
            ],
        }
    )["job_id"]


def test_inmemory_reassignment_is_atomic_on_conflict_and_exact_revision() -> None:
    repository = InMemoryFmsRepository()
    job_a, job_b = _job(repository, "A"), _job(repository, "B")
    repository.assign_job_resources(job_a, ASSIGNMENT)
    repository.assign_job_resources(
        job_b,
        {
            "revision": 1,
            "mobile_id": "PK_02",
            "omx_id": "OMX_02",
            "packing_dock_code": "PACKING-01-DOCK-02",
            "charger_code": "TRIHOUSE-TEST-01-CHG-02",
        },
    )

    with pytest.raises(ResourceUnavailable):
        repository.assign_job_resources(
            job_a, {**ASSIGNMENT, "revision": 2, "packing_dock_code": "PACKING-01-DOCK-02"}
        )

    assert repository.get_job(job_a)["context"]["assignment"] == ASSIGNMENT
    assert repository._reserved_assignment_resources["PACKING-01-DOCK-01"] == job_a
    with pytest.raises(ResourceAssignmentConflict, match="ASSIGNMENT_REVISION_GAP"):
        repository.assign_job_resources(job_a, {**ASSIGNMENT, "revision": 3})


def test_inmemory_reassignment_rejects_active_step_and_serializes_concurrency() -> None:
    repository = InMemoryFmsRepository()
    job_id = _job(repository, "ACTIVE")
    repository.assign_job_resources(job_id, ASSIGNMENT)
    step_id = repository.get_job(job_id)["steps"][0]["job_step_id"]
    repository._steps[step_id]["state"] = "running"
    with pytest.raises(ResourceAssignmentConflict, match="ASSIGNMENT_ALREADY_EXECUTING"):
        repository.assign_job_resources(job_id, {**ASSIGNMENT, "revision": 2})
    repository._steps[step_id]["state"] = "pending"

    def reassign(dock: str):
        try:
            return repository.assign_job_resources(
                job_id, {**ASSIGNMENT, "revision": 2, "packing_dock_code": dock}
            )
        except ResourceAssignmentConflict as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reassign, ("PACKING-01-DOCK-01", "PACKING-01-DOCK-02")))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ResourceAssignmentConflict) for result in results) == 1


@pytest.mark.parametrize(
    ("code", "field", "value", "reason"),
    [
        ("PACKING-01-DOCK-01", "state", "blocked", "PACKING_DOCK_UNAVAILABLE"),
        ("PACKING-01-DOCK-01", "location_type", "waypoint", "PACKING_DOCK_TYPE_MISMATCH"),
        ("TRIHOUSE-TEST-01-CHG-01", "state", "maintenance", "CHARGER_UNAVAILABLE"),
        ("TRIHOUSE-TEST-01-CHG-01", "location_type", "waypoint", "CHARGER_TYPE_MISMATCH"),
    ],
)
def test_inmemory_validates_location_type_role_and_state(code, field, value, reason) -> None:
    repository = InMemoryFmsRepository()
    job_id = _job(repository, reason)
    repository._assignment_locations[code][field] = value

    with pytest.raises(ResourceAssignmentConflict, match=reason):
        repository.assign_job_resources(job_id, ASSIGNMENT)


def test_inmemory_rejects_same_packing_and_charger_location() -> None:
    repository = InMemoryFmsRepository()
    job_id = _job(repository, "SAME")
    changed = {**ASSIGNMENT, "packing_dock_code": ASSIGNMENT["charger_code"]}
    with pytest.raises(ResourceAssignmentConflict, match="PACKING_DOCK_CHARGER_MUST_DIFFER"):
        repository.assign_job_resources(job_id, changed)

