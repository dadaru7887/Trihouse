"""Claim and outcome contract for the OMX/FMS executor worker.

Before these routes existed, `arm` and `fms` steps had no way to finish: the
outbox filled with `omx` and `pinky` rows that nothing could claim, and no code
path moved those steps out of `pending`. Navigation kept its own terminal path
through the robot's `task_event` stream, and these tests hold that boundary.
"""

from fastapi.testclient import TestClient

from fms_gateway.app.main import create_app
from fms_gateway.app.repositories import InMemoryFmsRepository


def executor_job() -> dict[str, object]:
    return {
        "job_code": "EXEC-2026-001",
        "operation_type": "outbound",
        "priority": "normal",
        "context": {},
        "steps": [
            {
                "step_no": 10,
                "action_type": "pick",
                "executor_type": "arm",
                "target_location_id": 12,
                "input": {"sku": "SKU-1"},
            },
            {
                "step_no": 20,
                "action_type": "navigate",
                "executor_type": "mobile",
                "target_location_id": 12,
                "input": {"waypoint": "PACK-01"},
            },
        ],
    }


def _client() -> tuple[TestClient, InMemoryFmsRepository]:
    repository = InMemoryFmsRepository()
    return TestClient(create_app(repository)), repository


def _dispatch(client: TestClient, job_step_id: int, key: str) -> None:
    response = client.post(
        f"/internal/v1/job-steps/{job_step_id}/dispatch",
        json={"actor": "control-tower", "assigned_device_id": "OMX_01"},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 200, response.text


def _outcome_body(**overrides) -> dict[str, object]:
    body = {
        "outcome": "succeeded",
        "assignment_revision": 0,
        "method_code": "OMX_PICK_FIXTURE",
        "actor_device_id": "OMX_01",
        "reason_code": "PICK_CONFIRMED",
        "metrics": {"duration": {"total_ms": 4200}},
    }
    body.update(overrides)
    return body


def _pick_step(client: TestClient) -> int:
    created = client.post("/internal/v1/jobs", json=executor_job())
    assert created.status_code == 201, created.text
    return created.json()["steps"][0]["job_step_id"]


def test_executor_claims_only_the_channels_it_asks_for() -> None:
    """An OMX worker must not steal the RMF worker's navigation dispatches."""
    client, _ = _client()
    step_id = _pick_step(client)
    _dispatch(client, step_id, "dispatch-pick-1")

    claimed = client.post(
        "/internal/v1/executor/dispatches/claim",
        json={"worker_id": "executor-1", "channels": ["omx"], "limit": 10},
    )

    assert claimed.status_code == 200, claimed.text
    dispatches = claimed.json()["dispatches"]
    assert [item["channel"] for item in dispatches] == ["omx"]
    assert dispatches[0]["job_step_id"] == step_id


def test_a_claim_carries_the_step_context_the_executor_needs() -> None:
    """The executor must not have to re-query the Gateway to act on a claim.

    `assigned_device_id` and `assignment` stay empty here because this fixture
    creates the job directly rather than through an order, and it is
    `assign_job_resources` that stamps devices onto steps. The fields are still
    present, which is what the executor depends on.
    """
    client, _ = _client()
    step_id = _pick_step(client)
    _dispatch(client, step_id, "dispatch-pick-1")

    claimed = client.post(
        "/internal/v1/executor/dispatches/claim",
        json={"worker_id": "executor-1", "channels": ["omx", "pinky"], "limit": 10},
    ).json()["dispatches"][0]

    assert claimed["action_type"] == "pick"
    assert claimed["executor_type"] == "arm"
    assert claimed["assignment"] == {}
    assert claimed["payload"]["input"] == {"sku": "SKU-1"}


def test_a_claimed_dispatch_is_not_handed_to_a_second_worker() -> None:
    client, _ = _client()
    step_id = _pick_step(client)
    _dispatch(client, step_id, "dispatch-pick-1")
    body = {"worker_id": "executor-1", "channels": ["omx"], "limit": 10}

    first = client.post("/internal/v1/executor/dispatches/claim", json=body).json()
    second = client.post("/internal/v1/executor/dispatches/claim", json=body).json()

    assert len(first["dispatches"]) == 1
    assert second["dispatches"] == []


def test_a_reported_outcome_moves_the_step_out_of_pending() -> None:
    """The gap this route closes: an arm step could never reach a terminal state."""
    client, _ = _client()
    step_id = _pick_step(client)
    _dispatch(client, step_id, "dispatch-pick-1")

    reported = client.post(
        f"/internal/v1/job-steps/{step_id}/outcome",
        json=_outcome_body(),
        headers={"Idempotency-Key": "outcome-pick-1"},
    )

    assert reported.status_code == 200, reported.text
    assert reported.json()["state"] == "succeeded"
    detail = client.get("/api/v1/jobs/1").json()
    assert detail["steps"][0]["state"] == "succeeded"


def test_repeating_an_outcome_returns_the_first_answer() -> None:
    """A worker that retries after a lost response must not double-report."""
    client, _ = _client()
    step_id = _pick_step(client)
    _dispatch(client, step_id, "dispatch-pick-1")
    headers = {"Idempotency-Key": "outcome-pick-1"}

    first = client.post(
        f"/internal/v1/job-steps/{step_id}/outcome", json=_outcome_body(), headers=headers
    )
    second = client.post(
        f"/internal/v1/job-steps/{step_id}/outcome", json=_outcome_body(), headers=headers
    )

    assert first.json() == second.json()


def test_the_same_key_with_a_different_report_is_a_conflict() -> None:
    client, _ = _client()
    step_id = _pick_step(client)
    _dispatch(client, step_id, "dispatch-pick-1")
    headers = {"Idempotency-Key": "outcome-pick-1"}
    client.post(
        f"/internal/v1/job-steps/{step_id}/outcome", json=_outcome_body(), headers=headers
    )

    changed = client.post(
        f"/internal/v1/job-steps/{step_id}/outcome",
        json=_outcome_body(outcome="failed", failure_domain="manipulation"),
        headers=headers,
    )

    assert changed.status_code == 409


def test_a_navigation_step_cannot_be_closed_by_an_executor() -> None:
    """Navigation terminates through task_event, which verifies telemetry and stop
    conditions. Allowing this route to close it would bypass all of that."""
    client, _ = _client()
    created = client.post("/internal/v1/jobs", json=executor_job()).json()
    navigate_step = created["steps"][1]["job_step_id"]

    reported = client.post(
        f"/internal/v1/job-steps/{navigate_step}/outcome",
        json=_outcome_body(actor_device_id="PK_01"),
        headers={"Idempotency-Key": "outcome-nav-1"},
    )

    assert reported.status_code == 409
    assert reported.json()["detail"]["code"] == "MOBILE_STEP_USES_TASK_EVENT"


def test_a_stale_assignment_revision_is_rejected() -> None:
    """Late results from a superseded assignment must not close a live step."""
    client, _ = _client()
    step_id = _pick_step(client)
    _dispatch(client, step_id, "dispatch-pick-1")

    reported = client.post(
        f"/internal/v1/job-steps/{step_id}/outcome",
        json=_outcome_body(assignment_revision=7),
        headers={"Idempotency-Key": "outcome-pick-1"},
    )

    assert reported.status_code == 409
    assert reported.json()["detail"]["code"] == "STALE_ASSIGNMENT"


def test_an_already_finished_step_is_not_reopened() -> None:
    client, _ = _client()
    step_id = _pick_step(client)
    _dispatch(client, step_id, "dispatch-pick-1")
    client.post(
        f"/internal/v1/job-steps/{step_id}/outcome",
        json=_outcome_body(),
        headers={"Idempotency-Key": "outcome-pick-1"},
    )

    again = client.post(
        f"/internal/v1/job-steps/{step_id}/outcome",
        json=_outcome_body(),
        headers={"Idempotency-Key": "outcome-pick-2"},
    )

    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "STEP_NOT_OPEN"


def test_an_unknown_step_is_not_found() -> None:
    client, _ = _client()

    reported = client.post(
        "/internal/v1/job-steps/999999/outcome",
        json=_outcome_body(),
        headers={"Idempotency-Key": "outcome-missing"},
    )

    assert reported.status_code == 404


def test_a_failed_outcome_must_name_its_failure_domain() -> None:
    """`none` on a failure would erase which layer to investigate."""
    client, _ = _client()
    step_id = _pick_step(client)
    _dispatch(client, step_id, "dispatch-pick-1")

    reported = client.post(
        f"/internal/v1/job-steps/{step_id}/outcome",
        json=_outcome_body(outcome="failed"),
        headers={"Idempotency-Key": "outcome-pick-1"},
    )

    assert reported.status_code == 422


def test_a_claim_requires_at_least_one_channel() -> None:
    client, _ = _client()

    claimed = client.post(
        "/internal/v1/executor/dispatches/claim",
        json={"worker_id": "executor-1", "channels": [], "limit": 10},
    )

    assert claimed.status_code == 422


def test_a_lease_that_expires_returns_the_work_to_the_queue() -> None:
    """A worker that dies mid-execution must not strand its dispatch forever.

    A claim marks the row `sent`, and a claim only ever looked at `pending`, so
    before the lease existed that row could never be handed to anyone again.
    """
    client, repository = _client()
    step_id = _pick_step(client)
    _dispatch(client, step_id, "dispatch-pick-1")
    body = {"worker_id": "executor-1", "channels": ["omx"], "limit": 10}
    assert len(client.post("/internal/v1/executor/dispatches/claim", json=body).json()["dispatches"]) == 1
    assert client.post("/internal/v1/executor/dispatches/claim", json=body).json()["dispatches"] == []

    repository.expire_dispatch_leases()

    reclaimed = client.post("/internal/v1/executor/dispatches/claim", json=body).json()
    assert [item["job_step_id"] for item in reclaimed["dispatches"]] == [step_id]


def test_a_message_that_keeps_killing_its_worker_stops_being_reclaimed() -> None:
    """Without a cap, a poison pill is reclaimed and re-executed forever."""
    client, repository = _client()
    step_id = _pick_step(client)
    _dispatch(client, step_id, "dispatch-pick-1")
    body = {"worker_id": "executor-1", "channels": ["omx"], "limit": 10}

    seen = 0
    for _ in range(repository.DISPATCH_MAX_ATTEMPTS + 3):
        claimed = client.post("/internal/v1/executor/dispatches/claim", json=body).json()
        seen += len(claimed["dispatches"])
        repository.expire_dispatch_leases()

    assert seen == repository.DISPATCH_MAX_ATTEMPTS


def test_a_live_claim_is_not_taken_from_the_worker_holding_it() -> None:
    """Reclaiming early would send the same command to the arm twice."""
    client, _ = _client()
    step_id = _pick_step(client)
    _dispatch(client, step_id, "dispatch-pick-1")
    body = {"worker_id": "executor-1", "channels": ["omx"], "limit": 10}
    client.post("/internal/v1/executor/dispatches/claim", json=body)

    again = client.post(
        "/internal/v1/executor/dispatches/claim",
        json={"worker_id": "executor-2", "channels": ["omx"], "limit": 10},
    ).json()

    assert again["dispatches"] == []
