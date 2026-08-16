from fastapi.testclient import TestClient

from fms_gateway.app.main import create_app
from fms_gateway.app.repositories import InMemoryFmsRepository


def outbound_job() -> dict[str, object]:
    return {
        "job_code": "OUT-2026-001",
        "operation_type": "outbound",
        "priority": "high",
        "external_reference": "order-4481",
        "context": {"wave": "morning"},
        "steps": [
            {
                "step_no": 1,
                "action_type": "navigate",
                "executor_type": "mobile",
                "target_location_id": 12,
                "input": {"waypoint": "PACK-01"},
            },
            {
                "step_no": 2,
                "action_type": "load",
                "executor_type": "arm",
                "target_location_id": 12,
                "input": {"sku": "SKU-1"},
            },
        ],
    }


def test_create_job_returns_generated_hierarchy_and_timeline_event():
    client = TestClient(create_app(InMemoryFmsRepository()))

    created = client.post("/internal/v1/jobs", json=outbound_job())

    assert created.status_code == 201
    assert created.json() == {
        "job_id": 1,
        "job_code": "OUT-2026-001",
        "state": "queued",
        "steps": [
            {
                "job_step_id": 1,
                "step_no": 1,
                "action_type": "navigate",
                "executor_type": "mobile",
                "target_location_id": 12,
                "state": "pending",
            },
            {
                "job_step_id": 2,
                "step_no": 2,
                "action_type": "load",
                "executor_type": "arm",
                "target_location_id": 12,
                "state": "pending",
            },
        ],
    }

    detail = client.get("/api/v1/jobs/1")
    assert detail.status_code == 200
    assert detail.json()["context"] == {"wave": "morning"}
    assert [step["step_no"] for step in detail.json()["steps"]] == [1, 2]

    timeline = client.get("/api/v1/jobs/1/timeline")
    assert timeline.status_code == 200
    assert timeline.json()["job_id"] == 1
    assert [event["event_type"] for event in timeline.json()["events"]] == [
        "job.created"
    ]


def test_create_job_rejects_non_increasing_step_order():
    client = TestClient(create_app(InMemoryFmsRepository()))
    body = outbound_job()
    body["steps"] = [body["steps"][1], body["steps"][0]]

    response = client.post("/internal/v1/jobs", json=body)

    assert response.status_code == 422


def test_dispatch_is_idempotent_and_rejects_a_non_current_step():
    client = TestClient(create_app(InMemoryFmsRepository()))
    steps = client.post("/internal/v1/jobs", json=outbound_job()).json()["steps"]
    request = {
        "headers": {"Idempotency-Key": "dispatch-out-1-step-1"},
        "json": {"actor": "control-tower", "assigned_device_id": "PK_01"},
    }

    first = client.post(
        f"/internal/v1/job-steps/{steps[0]['job_step_id']}/dispatch", **request
    )
    repeated = client.post(
        f"/internal/v1/job-steps/{steps[0]['job_step_id']}/dispatch", **request
    )
    blocked = client.post(
        f"/internal/v1/job-steps/{steps[1]['job_step_id']}/dispatch",
        headers={"Idempotency-Key": "dispatch-out-1-step-2"},
        json={"actor": "control-tower"},
    )

    assert first.status_code == repeated.status_code == 200
    assert repeated.json() == first.json()
    assert first.json()["channel"] == "rmf"
    assert first.json()["message_type"] == "dispatch_task_request"
    assert first.json()["state"] == "pending"
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "job step is not the current pending step"


def test_dispatch_rejects_reusing_key_for_different_request():
    client = TestClient(create_app(InMemoryFmsRepository()))
    step_id = client.post("/internal/v1/jobs", json=outbound_job()).json()["steps"][0][
        "job_step_id"
    ]
    headers = {"Idempotency-Key": "same-key"}

    assert client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers=headers,
        json={"actor": "control-tower", "assigned_device_id": "PK_01"},
    ).status_code == 200
    conflict = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers=headers,
        json={"actor": "control-tower", "assigned_device_id": "PK_02"},
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "idempotency key was already used for another request"


def test_failed_current_step_requires_explicit_retry_and_new_dispatch_key():
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository))
    step_id = client.post("/internal/v1/jobs", json=outbound_job()).json()["steps"][0][
        "job_step_id"
    ]
    client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": "first-attempt"},
        json={"actor": "control-tower"},
    )
    repository.record_step_outcome(step_id, "failed")

    accidental = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": "retry-without-intent"},
        json={"actor": "control-tower"},
    )
    retry = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": "second-attempt"},
        json={"actor": "control-tower", "retry": True},
    )

    assert accidental.status_code == 409
    assert retry.status_code == 200
    assert retry.json()["payload"]["request"]["retry"] is True


def test_failed_step_can_retry_after_previous_rmf_dispatch_was_acknowledged():
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository))
    step_id = client.post("/internal/v1/jobs", json=outbound_job()).json()["steps"][0][
        "job_step_id"
    ]
    first = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": "first-rmf-attempt"},
        json={"actor": "control-tower", "assigned_device_id": "PK_01"},
    ).json()
    client.post("/internal/v1/rmf/dispatches/claim", json={"worker_id": "worker"})
    accepted = client.post(
        f"/internal/v1/rmf/dispatches/{first['message_id']}/acceptance",
        json={
            "accepted": True,
            "rmf_task_id": "rmf-first",
            "assigned_device_id": "PK_01",
        },
    )
    assert accepted.status_code == 200
    repository.record_step_outcome(step_id, "failed")

    retry = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": "second-rmf-attempt"},
        json={"actor": "control-tower", "assigned_device_id": "PK_01", "retry": True},
    )

    assert retry.status_code == 200
    assert retry.json()["message_id"] != first["message_id"]


def test_unknown_job_and_step_return_not_found():
    client = TestClient(create_app(InMemoryFmsRepository()))

    assert client.get("/api/v1/jobs/404").status_code == 404
    assert client.get("/api/v1/jobs/404/timeline").status_code == 404
    assert client.post(
        "/internal/v1/job-steps/404/dispatch",
        headers={"Idempotency-Key": "missing"},
        json={"actor": "control-tower"},
    ).status_code == 404


def test_command_claim_returns_exact_idempotent_task_context():
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository))
    step_id = client.post("/internal/v1/jobs", json=outbound_job()).json()["steps"][0][
        "job_step_id"
    ]
    repository.record_rmf_acceptance(step_id, "rmf-task-10-31", "PK_01")
    body = {
        "robot_id": "PK_01",
        "execution_id": "rmf-execution-9",
        "map_revision": "warehouse:abc123",
    }

    first = client.post(
        "/internal/v1/rmf/tasks/rmf-task-10-31/commands/claim", json=body
    )
    repeated = client.post(
        "/internal/v1/rmf/tasks/rmf-task-10-31/commands/claim", json=body
    )

    assert first.status_code == repeated.status_code == 200
    assert repeated.json() == first.json()
    context = first.json()["task_context"]
    assert context == {
        "active": True,
        "job_id": 1,
        "job_step_id": step_id,
        "assignment_revision": 1,
        "rmf_task_id": "rmf-task-10-31",
        "command_id": context["command_id"],
        "map_revision": "warehouse:abc123",
        "command_source": "rmf",
    }


def test_command_claim_rejects_unmapped_task_and_changed_identity():
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository))
    step_id = client.post("/internal/v1/jobs", json=outbound_job()).json()["steps"][0][
        "job_step_id"
    ]
    repository.record_rmf_acceptance(step_id, "rmf-task-10-31", "PK_01")

    assert client.post(
        "/internal/v1/rmf/tasks/missing/commands/claim",
        json={
            "robot_id": "PK_01",
            "execution_id": "execution-1",
            "map_revision": "warehouse:abc123",
        },
    ).status_code == 404
    assert client.post(
        "/internal/v1/rmf/tasks/rmf-task-10-31/commands/claim",
        json={
            "robot_id": "PK_01",
            "execution_id": "execution-1",
            "map_revision": "warehouse:abc123",
        },
    ).status_code == 200
    conflict = client.post(
        "/internal/v1/rmf/tasks/rmf-task-10-31/commands/claim",
        json={
            "robot_id": "PK_02",
            "execution_id": "execution-1",
            "map_revision": "warehouse:abc123",
        },
    )

    assert conflict.status_code == 409


def test_rmf_worker_claim_and_acceptance_map_dispatch_for_command_claim():
    client = TestClient(create_app(InMemoryFmsRepository()))
    step_id = client.post("/internal/v1/jobs", json=outbound_job()).json()["steps"][0][
        "job_step_id"
    ]
    dispatch = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": "dispatch-to-rmf"},
        json={"actor": "control-tower"},
    ).json()

    claimed = client.post(
        "/internal/v1/rmf/dispatches/claim",
        json={"worker_id": "rmf-worker-1", "limit": 1},
    )
    accepted = client.post(
        f"/internal/v1/rmf/dispatches/{dispatch['message_id']}/acceptance",
        json={
            "accepted": True,
            "rmf_task_id": "rmf-task-10-31",
            "assigned_device_id": "PK_01",
        },
    )
    command = client.post(
        "/internal/v1/rmf/tasks/rmf-task-10-31/commands/claim",
        json={
            "robot_id": "PK_01",
            "execution_id": "execution-1",
            "map_revision": "warehouse:abc123",
        },
    )

    assert claimed.status_code == 200
    assert claimed.json()["dispatches"][0]["message_id"] == dispatch["message_id"]
    assert claimed.json()["dispatches"][0]["state"] == "sent"
    assert claimed.json()["dispatches"][0]["payload"]["target_waypoint"] == "PACK-01"
    assert isinstance(
        claimed.json()["dispatches"][0]["payload"]["request_time_ms"], int
    )
    assert accepted.json() == {
        "message_id": dispatch["message_id"],
        "job_step_id": step_id,
        "state": "acknowledged",
        "rmf_task_id": "rmf-task-10-31",
    }
    assert command.status_code == 200


def test_rmf_acceptance_cannot_substitute_control_tower_assignment():
    """RMF traffic coordination cannot overwrite the persisted Pinky or revision."""
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository))
    step_id = client.post("/internal/v1/jobs", json=outbound_job()).json()["steps"][0][
        "job_step_id"
    ]
    assigned = client.post(
        "/internal/v1/jobs/1/assignment",
        json={
            "revision": 1,
            "mobile_id": "PK_01",
            "omx_id": "OMX_01",
            "packing_dock_code": "PACKING-01-DOCK-01",
            "charger_code": "TRIHOUSE-TEST-01-CHG-01",
        },
    )
    dispatch = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": "dispatch-owned-assignment"},
        json={"actor": "control-tower", "assigned_device_id": "PK_01"},
    ).json()
    client.post("/internal/v1/rmf/dispatches/claim", json={"worker_id": "worker"})

    rejected = client.post(
        f"/internal/v1/rmf/dispatches/{dispatch['message_id']}/acceptance",
        json={
            "accepted": True,
            "rmf_task_id": "rmf-substitute",
            "assigned_device_id": "PK_02",
        },
    )
    detail = client.get("/api/v1/jobs/1").json()

    assert assigned.status_code == 200
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "RMF_ASSIGNED_DEVICE_MISMATCH"
    assert detail["steps"][0]["assigned_device_id"] == "PK_01"
    assert detail["steps"][0]["assignment_revision"] == 1


def test_rejected_rmf_dispatch_is_failed_without_mapping():
    client = TestClient(create_app(InMemoryFmsRepository()))
    step_id = client.post("/internal/v1/jobs", json=outbound_job()).json()["steps"][0][
        "job_step_id"
    ]
    dispatch = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": "dispatch-rejected"},
        json={"actor": "control-tower"},
    ).json()
    client.post(
        "/internal/v1/rmf/dispatches/claim",
        json={"worker_id": "rmf-worker-1"},
    )

    rejected = client.post(
        f"/internal/v1/rmf/dispatches/{dispatch['message_id']}/acceptance",
        json={"accepted": False, "detail": "RMF rejected request"},
    )

    assert rejected.status_code == 200
    assert rejected.json()["state"] == "failed"
    assert rejected.json()["rmf_task_id"] is None


def test_rmf_acceptance_replay_requires_the_same_task_and_robot_identity():
    client = TestClient(create_app(InMemoryFmsRepository()))
    step_id = client.post("/internal/v1/jobs", json=outbound_job()).json()["steps"][0][
        "job_step_id"
    ]
    dispatch = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": "dispatch-replay"},
        json={"actor": "control-tower", "assigned_device_id": "PK_01"},
    ).json()
    client.post("/internal/v1/rmf/dispatches/claim", json={"worker_id": "worker"})
    path = f"/internal/v1/rmf/dispatches/{dispatch['message_id']}/acceptance"
    body = {
        "accepted": True,
        "rmf_task_id": "rmf-task-one",
        "assigned_device_id": "PK_01",
    }

    first = client.post(path, json=body)
    repeated = client.post(path, json=body)
    conflict = client.post(
        path,
        json={**body, "rmf_task_id": "rmf-task-other"},
    )

    assert first.status_code == repeated.status_code == 200
    assert repeated.json() == first.json()
    assert conflict.status_code == 409


def test_pending_rmf_booking_replay_requires_the_same_task_id():
    client = TestClient(create_app(InMemoryFmsRepository()))
    step_id = client.post("/internal/v1/jobs", json=outbound_job()).json()["steps"][0][
        "job_step_id"
    ]
    dispatch = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": "dispatch-pending-booking-replay"},
        json={"actor": "control-tower"},
    ).json()
    client.post("/internal/v1/rmf/dispatches/claim", json={"worker_id": "worker"})
    path = f"/internal/v1/rmf/dispatches/{dispatch['message_id']}/acceptance"
    pending = {"accepted": False, "rmf_task_id": "booking-one"}

    first = client.post(path, json=pending)
    repeated = client.post(path, json=pending)
    conflict = client.post(
        path,
        json={"accepted": False, "rmf_task_id": "booking-other"},
    )

    assert first.status_code == repeated.status_code == 200
    assert repeated.json() == first.json()
    assert conflict.status_code == 409


def test_pending_rmf_booking_can_only_accept_the_booked_task_id():
    client = TestClient(create_app(InMemoryFmsRepository()))
    step_id = client.post("/internal/v1/jobs", json=outbound_job()).json()["steps"][0][
        "job_step_id"
    ]
    dispatch = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": "dispatch-pending-booking-accept"},
        json={"actor": "control-tower"},
    ).json()
    client.post("/internal/v1/rmf/dispatches/claim", json={"worker_id": "worker"})
    path = f"/internal/v1/rmf/dispatches/{dispatch['message_id']}/acceptance"
    client.post(path, json={"accepted": False, "rmf_task_id": "booking-one"})

    conflict = client.post(
        path,
        json={
            "accepted": True,
            "rmf_task_id": "booking-other",
            "assigned_device_id": "PK_01",
        },
    )
    accepted = client.post(
        path,
        json={
            "accepted": True,
            "rmf_task_id": "booking-one",
            "assigned_device_id": "PK_01",
        },
    )

    assert conflict.status_code == 409
    assert accepted.status_code == 200
    assert accepted.json()["state"] == "acknowledged"
    assert accepted.json()["rmf_task_id"] == "booking-one"


def test_pending_rmf_booking_cannot_be_failed_by_an_unidentified_negative():
    client = TestClient(create_app(InMemoryFmsRepository()))
    step_id = client.post("/internal/v1/jobs", json=outbound_job()).json()["steps"][0][
        "job_step_id"
    ]
    dispatch = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": "dispatch-pending-booking-negative"},
        json={"actor": "control-tower"},
    ).json()
    client.post("/internal/v1/rmf/dispatches/claim", json={"worker_id": "worker"})
    path = f"/internal/v1/rmf/dispatches/{dispatch['message_id']}/acceptance"
    pending = {"accepted": False, "rmf_task_id": "booking-one"}
    assert client.post(path, json=pending).status_code == 200

    unidentified_negative = client.post(
        path,
        json={"accepted": False, "detail": "booking outcome omitted"},
    )
    still_pending = client.post(path, json=pending)

    assert unidentified_negative.status_code == 409
    assert still_pending.status_code == 200
    assert still_pending.json()["state"] == "sent"
    assert still_pending.json()["rmf_task_id"] == "booking-one"
