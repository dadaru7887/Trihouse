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
                "input": {"dependencies": [], "waypoint": "PACK-01"},
            },
            {
                "step_no": 2,
                "action_type": "load",
                "executor_type": "arm",
                "target_location_id": 12,
                "input": {"dependencies": [1], "sku": "SKU-1"},
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


def test_dispatch_allows_two_independent_root_steps_before_either_completes():
    client = TestClient(create_app(InMemoryFmsRepository()))
    body = outbound_job()
    body["steps"] = [
        {
            "step_no": 10,
            "action_type": "prepare",
            "executor_type": "arm",
            "input": {"dependencies": []},
        },
        {
            "step_no": 20,
            "action_type": "navigate",
            "executor_type": "mobile",
            "input": {"dependencies": []},
        },
        {
            "step_no": 30,
            "action_type": "load",
            "executor_type": "fms",
            "input": {"dependencies": [10, 20]},
        },
    ]
    steps = client.post("/internal/v1/jobs", json=body).json()["steps"]

    arm = client.post(
        f"/internal/v1/job-steps/{steps[0]['job_step_id']}/dispatch",
        headers={"Idempotency-Key": "dispatch-parallel-arm"},
        json={"actor": "control-tower"},
    )
    mobile = client.post(
        f"/internal/v1/job-steps/{steps[1]['job_step_id']}/dispatch",
        headers={"Idempotency-Key": "dispatch-parallel-mobile"},
        json={"actor": "control-tower", "assigned_device_id": "PK_01"},
    )
    join = client.post(
        f"/internal/v1/job-steps/{steps[2]['job_step_id']}/dispatch",
        headers={"Idempotency-Key": "dispatch-parallel-join"},
        json={"actor": "control-tower"},
    )

    assert arm.status_code == mobile.status_code == 200
    assert join.status_code == 409


def test_dispatch_rejects_a_step_without_explicit_dependencies():
    client = TestClient(create_app(InMemoryFmsRepository()))
    body = outbound_job()
    body["steps"] = [
        {
            "step_no": 10,
            "action_type": "prepare",
            "executor_type": "arm",
            "input": {},
        }
    ]
    step_id = client.post("/internal/v1/jobs", json=body).json()["steps"][0][
        "job_step_id"
    ]

    response = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": "dispatch-missing-dependencies"},
        json={"actor": "control-tower"},
    )

    assert response.status_code == 409


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


def test_assignment_accepts_every_workcell_required_by_mixed_zone_steps():
    """EN: omx_ids exposes every atomic reservation for a mixed order.

    KO: omx_ids는 혼합 주문에서 원자적으로 예약한 모든 작업셀을 보여준다.
    """
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository))
    body = outbound_job()
    body["steps"] = [
        {
            "step_no": 10,
            "action_type": "prepare",
            "executor_type": "arm",
            "input": {"dependencies": [], "omx_id": "OMX_01"},
        },
        {
            "step_no": 20,
            "action_type": "navigate",
            "executor_type": "mobile",
            "input": {"dependencies": [10]},
        },
        {
            "step_no": 30,
            "action_type": "prepare",
            "executor_type": "arm",
            "input": {"dependencies": [20], "omx_id": "OMX_02"},
        },
        {
            "step_no": 40,
            "action_type": "navigate",
            "executor_type": "mobile",
            "input": {"dependencies": [30]},
        },
    ]
    job_id = client.post("/internal/v1/jobs", json=body).json()["job_id"]

    response = client.post(
        f"/internal/v1/jobs/{job_id}/assignment",
        json={
            "revision": 1,
            "mobile_id": "PK_01",
            "omx_id": "OMX_01",
            "omx_ids": ["OMX_01", "OMX_02"],
            "packing_dock_code": "PACKING-01-DOCK-01",
            "charger_code": "TRIHOUSE-TEST-01-CHG-01",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["omx_ids"] == ["OMX_01", "OMX_02"]
    detail = client.get(f"/api/v1/jobs/{job_id}").json()
    assert detail["context"]["assignment"]["omx_ids"] == ["OMX_01", "OMX_02"]
    assert [step["assigned_device_id"] for step in detail["steps"]] == [
        "OMX_01", "PK_01", "OMX_02", "PK_01",
    ]


def test_assignment_rejects_a_workcell_list_that_omits_a_later_zone():
    """EN: Reject a list that omits an OMX needed later in the route.

    KO: 경로 후반에 필요한 OMX가 누락된 목록은 거부한다.
    """
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository))
    body = outbound_job()
    body["steps"] = [
        {
            "step_no": 10,
            "action_type": "prepare",
            "executor_type": "arm",
            "input": {"dependencies": [], "omx_id": "OMX_01"},
        },
        {
            "step_no": 20,
            "action_type": "prepare",
            "executor_type": "arm",
            "input": {"dependencies": [10], "omx_id": "OMX_02"},
        },
    ]
    job_id = client.post("/internal/v1/jobs", json=body).json()["job_id"]

    response = client.post(
        f"/internal/v1/jobs/{job_id}/assignment",
        json={
            "revision": 1,
            "mobile_id": "PK_01",
            "omx_id": "OMX_01",
            "omx_ids": ["OMX_01"],
            "packing_dock_code": "PACKING-01-DOCK-01",
            "charger_code": "TRIHOUSE-TEST-01-CHG-01",
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "OMX_ASSIGNMENT_MISMATCH"


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


def test_pending_rmf_booking_binds_the_task_id_to_the_step():
    """배정 대기 중에도 step 이 RMF task id 를 들고 있어야 한다.

    RMF 는 제출 즉시 booking 만 만들고 배정은 입찰이 끝난 뒤에 정해진다. 그
    배정을 나중에 되돌려 주는 observer 는 `job_steps.rmf_task_id` 로 step 을
    찾는다. 대기 상태에서 그 값을 비워 두면 observer 가 자기 작업을 알아보지
    못하고, outbox 는 재시도를 소진해 dead_letter 가 된다.
    """
    client = TestClient(create_app(InMemoryFmsRepository()))
    created = client.post("/internal/v1/jobs", json=outbound_job()).json()
    job_id = created["job_id"]
    step_id = created["steps"][0]["job_step_id"]
    dispatch = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": "dispatch-pending-binds-task"},
        json={"actor": "control-tower"},
    ).json()
    client.post("/internal/v1/rmf/dispatches/claim", json={"worker_id": "worker"})

    pending = client.post(
        f"/internal/v1/rmf/dispatches/{dispatch['message_id']}/acceptance",
        json={"accepted": False, "rmf_task_id": "compose.dispatch-abc123"},
    )

    assert pending.status_code == 200
    step = next(
        row
        for row in client.get(f"/api/v1/jobs/{job_id}").json()["steps"]
        if row["job_step_id"] == step_id
    )
    assert step["rmf_task_id"] == "compose.dispatch-abc123"


def test_rmf_task_update_settles_the_pending_dispatch_with_the_awarded_robot():
    """입찰이 끝난 뒤 도착한 RMF task 갱신이 대기 중이던 dispatch 를 확정한다.

    RMF 는 제출 즉시 booking 만 만들고 어느 로봇이 할지는 입찰이 끝나야 정해진다.
    그 결과를 되돌려 줄 경로가 없으면 outbox 는 `sent` 에 머물다 재시도를 소진해
    dead_letter 가 되고, 주문은 로봇을 움직이지 못한다.
    """
    client = TestClient(create_app(InMemoryFmsRepository()))
    created = client.post("/internal/v1/jobs", json=outbound_job()).json()
    job_id = created["job_id"]
    step_id = created["steps"][0]["job_step_id"]
    dispatch = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": "dispatch-task-update-settles"},
        json={"actor": "control-tower", "assigned_device_id": "PK_01"},
    ).json()
    client.post("/internal/v1/rmf/dispatches/claim", json={"worker_id": "worker"})
    client.post(
        f"/internal/v1/rmf/dispatches/{dispatch['message_id']}/acceptance",
        json={"accepted": False, "rmf_task_id": "compose.dispatch-award"},
    )

    settled = client.post(
        "/internal/v1/rmf/tasks/compose.dispatch-award/updates",
        json={
            "fleet_name": "project1_pinky",
            "robot_name": "PK_01",
            "rmf_status": "underway",
            "step_state": "running",
            "observed_at_ms": 1787060295000,
        },
    )

    assert settled.status_code == 200
    step = next(
        row
        for row in client.get(f"/api/v1/jobs/{job_id}").json()["steps"]
        if row["job_step_id"] == step_id
    )
    assert step["assigned_device_id"] == "PK_01"
    assert step["rmf_task_id"] == "compose.dispatch-award"


def test_rmf_task_update_for_an_unknown_task_is_rejected():
    """우리가 만들지 않은 RMF task 는 원장을 건드리지 못한다."""
    client = TestClient(create_app(InMemoryFmsRepository()))

    response = client.post(
        "/internal/v1/rmf/tasks/compose.dispatch-someone-else/updates",
        json={
            "fleet_name": "project1_pinky",
            "robot_name": "PK_01",
            "rmf_status": "underway",
            "step_state": "running",
            "observed_at_ms": 1787060295000,
        },
    )

    assert response.status_code == 404


def test_executor_claim_ignores_robot_command_records_on_the_same_channel():
    """`pinky` 채널에는 성격이 다른 두 가지가 흐른다. executor 는 자기 것만 집는다.

    `claim_command` 가 남기는 `execution_command` 는 로봇 명령 기록이지 executor 가
    실행할 작업이 아니다. 채널로만 고르면 executor 가 그것까지 집어 409 를 맞고
    `attempts` 만 올리다 dead_letter 로 민다. 2026-08-19 에 step 59 하나에
    `execution_command` 463행이 쌓이고 초당 수십 번 409 가 났다.
    """
    client = TestClient(create_app(InMemoryFmsRepository()))
    created = client.post("/internal/v1/jobs", json=outbound_job()).json()
    step_id = created["steps"][0]["job_step_id"]  # mobile / navigate
    dispatch = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": "dispatch-executor-channel"},
        json={"actor": "control-tower", "assigned_device_id": "PK_01"},
    ).json()
    client.post("/internal/v1/rmf/dispatches/claim", json={"worker_id": "rmf-worker"})
    client.post(
        f"/internal/v1/rmf/dispatches/{dispatch['message_id']}/acceptance",
        json={
            "accepted": True,
            "rmf_task_id": "compose.dispatch-exec-channel",
            "assigned_device_id": "PK_01",
        },
    )
    # 로봇이 명령을 claim 하면 같은 `pinky` 채널에 execution_command 가 남는다.
    claimed_command = client.post(
        "/internal/v1/rmf/tasks/compose.dispatch-exec-channel/commands/claim",
        json={
            "robot_id": "PK_01",
            "execution_id": "exec-1",
            "map_revision": "trihouse_test_01:rev",
        },
    )
    assert claimed_command.status_code == 200

    claimed = client.post(
        "/internal/v1/executor/dispatches/claim",
        json={"worker_id": "executor", "channels": ["omx", "pinky"], "limit": 10},
    ).json()["dispatches"]

    types = {row["message_type"] for row in claimed}
    assert "execution_command" not in types, types


def _claim_ready_step(client, *, robot: str = "PK_01", task: str = "compose.dispatch-idem"):
    """명령을 claim 할 수 있는 상태의 step 하나를 만든다."""
    created = client.post("/internal/v1/jobs", json=outbound_job()).json()
    step_id = created["steps"][0]["job_step_id"]
    dispatch = client.post(
        f"/internal/v1/job-steps/{step_id}/dispatch",
        headers={"Idempotency-Key": f"dispatch-{task}"},
        json={"actor": "control-tower", "assigned_device_id": robot},
    ).json()
    client.post("/internal/v1/rmf/dispatches/claim", json={"worker_id": "rmf-worker"})
    client.post(
        f"/internal/v1/rmf/dispatches/{dispatch['message_id']}/acceptance",
        json={"accepted": True, "rmf_task_id": task, "assigned_device_id": robot},
    )
    return step_id


def test_retrying_the_same_work_reuses_one_command_record():
    """재시도는 같은 명령이다. 실행 핸들이 새로 와도 원장에 행이 하나여야 한다.

    RMF 는 실패한 작업을 재시도할 때마다 새 execution handle 을 준다. 멱등키가
    그 handle 을 포함하면 재시도마다 새 행이 생기고 상한이 없어 무한히 쌓인다.
    2026-08-19 에 step 하나에 463행이 쌓이고 executor 가 409 를 초당 수십 번 맞았다.
    """
    client = TestClient(create_app(InMemoryFmsRepository()))
    step_id = _claim_ready_step(client)
    path = "/internal/v1/rmf/tasks/compose.dispatch-idem/commands/claim"
    body = {"robot_id": "PK_01", "map_revision": "trihouse_test_01:rev"}

    first = client.post(path, json={**body, "execution_id": "exec-1"})
    second = client.post(path, json={**body, "execution_id": "exec-2"})
    third = client.post(path, json={**body, "execution_id": "exec-3"})

    assert first.status_code == second.status_code == third.status_code == 200
    # 같은 일이므로 같은 명령이다.
    command_ids = {
        response.json()["task_context"]["command_id"]
        for response in (first, second, third)
    }
    assert len(command_ids) == 1, command_ids

    claimed = client.post(
        "/internal/v1/executor/dispatches/claim",
        json={"worker_id": "executor", "channels": ["pinky"], "limit": 50},
    ).json()["dispatches"]
    assert len(claimed) <= 1, len(claimed)


def test_another_robot_cannot_take_over_the_same_command():
    """로봇이 다르면 진짜 충돌이다. 재시도와 구분해야 한다."""
    client = TestClient(create_app(InMemoryFmsRepository()))
    _claim_ready_step(client, task="compose.dispatch-other-robot")
    path = "/internal/v1/rmf/tasks/compose.dispatch-other-robot/commands/claim"

    client.post(
        path,
        json={
            "robot_id": "PK_01",
            "execution_id": "exec-1",
            "map_revision": "trihouse_test_01:rev",
        },
    )
    conflict = client.post(
        path,
        json={
            "robot_id": "PK_02",
            "execution_id": "exec-2",
            "map_revision": "trihouse_test_01:rev",
        },
    )

    assert conflict.status_code == 409


def test_a_cancelled_job_cannot_be_given_resources_again():
    """종료된 job 에는 자원을 배정하지 않는다.

    `cancel_job` 은 step·예약·outbox 를 닫고 `jobs.state` 를 `cancelled` 로 쓴다.
    그런데 `assign_job_resources` 가 job 상태를 보지 않으면, 다음 주기의
    `job_runner` 가 그 job 을 다시 집어 `assigned` 로 되돌린다. 그러면 step 은
    `cancelled` 인데 job 은 `assigned` 인 상태가 남아 **로봇이 영원히 묶인다.**

    2026-08-19 에 job 15·16 이 그렇게 남아 뒤의 주문이 `no free robot` 으로
    줄줄이 밀렸다. 러너는 매 주기 `job runner blocked: step ... is cancelled` 를
    찍으며 자기가 되살린 job 에 스스로 막혔다.
    """
    client = TestClient(create_app(InMemoryFmsRepository()))
    job_id = client.post("/internal/v1/jobs", json=outbound_job()).json()["job_id"]
    assignment = {
        "revision": 1,
        "mobile_id": "PK_01",
        "omx_id": "OMX_01",
        "packing_dock_code": "PACKING-01-DOCK-01",
        "charger_code": "TRIHOUSE-TEST-01-CHG-01",
    }
    cancelled = client.post(
        f"/internal/v1/jobs/{job_id}/cancel",
        headers={"Idempotency-Key": "cancel-before-assign"},
        json={"reason": "operator stopped it", "requested_by": "W-OP-01"},
    )
    assert cancelled.status_code == 200

    revived = client.post(f"/internal/v1/jobs/{job_id}/assignment", json=assignment)

    assert revived.status_code == 409, revived.text
    state = client.get(f"/api/v1/jobs/{job_id}").json()["state"]
    assert state == "cancelled", state
