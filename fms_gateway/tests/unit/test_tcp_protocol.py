import asyncio
import json
import uuid

import pytest

from fms_gateway.app.tcp_protocol import (
    ProtocolRejected,
    ProtocolSession,
    TcpIngestionServer,
)
from fms_gateway.app.repositories import (
    InMemoryFmsRepository,
    MySqlFmsRepository,
    RuntimeContextConflict,
)


SESSION_ID = "550e8400-e29b-41d4-a716-446655440000"


def hello(**overrides):
    message = {
        "type": "hello",
        "schema_version": 3,
        "robot_id": "PK_01",
        "session_id": SESSION_ID,
    }
    message.update(overrides)
    return message


def status(sequence=1, **overrides):
    message = {
        "type": "robot_status",
        "schema_version": 3,
        "robot_id": "PK_01",
        "session_id": SESSION_ID,
        "sequence": sequence,
        "sent_at_ns": 123456789,
        "map_revision": "warehouse:abc123",
        "frame_id": "map",
        "pose": {"x": 1.2, "y": 3.4, "yaw": 0.5},
        "twist": {"linear_x_mps": 0.2, "angular_z_rps": 0.1},
        "navigation_state": 1,
        "task_progress": 0.4,
        "task_context": {
            "active": True,
            "job_id": 10,
            "job_step_id": 31,
            "assignment_revision": 2,
            "rmf_task_id": "rmf-task-10-31",
            "command_id": "1747bf84-6597-4b2f-9a71-bf65539b2836",
            "map_revision": "warehouse:abc123",
            "command_source": "rmf",
        },
        "battery_percentage": 74.5,
        "battery_condition": {
            "percentage": 74.5,
            "present": True,
            "power_supply_status": 2,
            "measurement_valid": True,
            "has_valid_sample": True,
            "telemetry_fresh": True,
        },
        "battery_policy": {
            "state": 1,
            "ready": True,
            "reason_code": "BATTERY_NORMAL",
            "detail": "battery permits normal work",
        },
        "safety_state": 0,
        "cargo_state": 1,
        "telemetry_valid": True,
        "execution_ready": True,
        "dispatchable": True,
        "ready": True,
        "errors": [],
    }
    message.update(overrides)
    return message


def test_hello_must_precede_status_and_bind_registered_robot():
    session = ProtocolSession(registered_robot_ids={"PK_01"})

    with pytest.raises(ProtocolRejected, match="HELLO_REQUIRED"):
        session.process(status())
    accepted = session.process(hello())

    assert accepted.action == "hello_accepted"
    assert accepted.robot_id == "PK_01"


def test_robot_status_v3_accepts_only_new_sequence_for_bound_session():
    session = ProtocolSession(registered_robot_ids={"PK_01"})
    session.process(hello())

    accepted = session.process(status(sequence=7))

    assert accepted.action == "robot_status"
    assert accepted.payload["sequence"] == 7
    with pytest.raises(ProtocolRejected, match="STALE_SEQUENCE"):
        session.process(status(sequence=7))
    with pytest.raises(ProtocolRejected, match="ROBOT_ID_MISMATCH"):
        session.process(status(sequence=8, robot_id="PK_02"))


def test_robot_status_rejects_incomplete_v3_schema():
    session = ProtocolSession(registered_robot_ids={"PK_01"})
    session.process(hello())
    incomplete = status()
    del incomplete["battery_condition"]

    with pytest.raises(ProtocolRejected, match="SCHEMA_INVALID"):
        session.process(incomplete)


def test_robot_status_rejects_non_numeric_or_non_finite_motion_facts():
    for bad_value in ("stopped", float("nan"), float("inf")):
        session = ProtocolSession(registered_robot_ids={"PK_01"})
        session.process(hello())
        invalid = status()
        invalid["twist"] = {
            "linear_x_mps": bad_value,
            "angular_z_rps": 0.0,
        }

        with pytest.raises(ProtocolRejected, match="SCHEMA_INVALID"):
            session.process(invalid)


def test_terminal_navigation_enum_is_not_projected_as_moving():
    terminal = status(navigation_state=2)

    assert MySqlFmsRepository._project_robot_state(terminal) == ("idle", "ok")


def test_task_event_validates_uuid_identity_and_task_context():
    session = ProtocolSession(registered_robot_ids={"PK_01"})
    session.process(hello())
    event = {
        "type": "task_event",
        "schema_version": 3,
        "event_id": str(uuid.uuid4()),
        "robot_id": "PK_01",
        "session_id": SESSION_ID,
        "event_type": "arrived",
        "reason_code": "WAYPOINT_REACHED",
        "method_code": "NAV2_DEFAULT",
        "detail": "arrived at PACK-01",
        "task_context": status()["task_context"],
    }

    accepted = session.process(event)

    assert accepted.action == "task_event"
    assert accepted.payload["event_type"] == "arrived"
    event["event_id"] = "not-a-uuid"
    with pytest.raises(ProtocolRejected, match="SCHEMA_INVALID"):
        session.process(event)


def test_heartbeat_is_accepted_after_hello():
    session = ProtocolSession(registered_robot_ids={"PK_01"})
    session.process(hello())

    accepted = session.process(
        {
            "type": "heartbeat",
            "schema_version": 3,
            "robot_id": "PK_01",
            "session_id": SESSION_ID,
        }
    )

    assert accepted.action == "heartbeat"


def test_tcp_server_acknowledges_ndjson_and_rejects_bad_schema():
    async def scenario():
        accepted = []
        server = TcpIngestionServer(
            host="127.0.0.1",
            port=0,
            registered_robot_ids=lambda: {"PK_01"},
            on_message=accepted.append,
        )
        await server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
            writer.write((json.dumps(hello()) + "\n").encode())
            await writer.drain()
            hello_ack = json.loads(await reader.readline())
            writer.write(
                (
                    json.dumps(
                        {
                            "type": "heartbeat",
                            "schema_version": 3,
                            "robot_id": "PK_01",
                            "session_id": SESSION_ID,
                        }
                    )
                    + "\n"
                ).encode()
            )
            await writer.drain()
            heartbeat_ack = json.loads(await reader.readline())
            status_message = status(sequence=8)
            writer.write((json.dumps(status_message) + "\n").encode())
            await writer.drain()
            status_ack = json.loads(await reader.readline())
            event_id = str(uuid.uuid4())
            event_message = {
                "type": "task_event", "schema_version": 3,
                "event_id": event_id, "robot_id": "PK_01",
                "session_id": SESSION_ID, "event_type": "started",
                "reason_code": "COMMAND_ACCEPTED", "method_code": "NAV2_DEFAULT",
                "detail": "started", "task_context": status_message["task_context"],
            }
            writer.write((json.dumps(event_message) + "\n").encode())
            await writer.drain()
            event_ack = json.loads(await reader.readline())
            writer.write(b'{"type":"robot_status"}\n')
            await writer.drain()
            rejection = json.loads(await reader.readline())
            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()
        return hello_ack, heartbeat_ack, status_ack, event_ack, rejection, accepted

    hello_ack, heartbeat_ack, status_ack, event_ack, rejection, accepted = asyncio.run(scenario())

    assert hello_ack == {"type": "ack", "action": "hello_accepted"}
    assert heartbeat_ack == {"type": "ack", "action": "heartbeat"}
    assert status_ack == {"type": "ack", "action": "robot_status", "sequence": 8}
    assert event_ack["type"] == "ack"
    assert event_ack["action"] == "task_event"
    assert isinstance(event_ack["event_id"], str)
    assert rejection == {
        "type": "event_rejected",
        "reason_code": "ROBOT_ID_MISMATCH",
    }
    assert [message.action for message in accepted] == [
        "hello_accepted",
        "heartbeat",
        "robot_status",
        "task_event",
    ]


def test_repository_ingestion_projects_status_and_terminal_task_event():
    repository = InMemoryFmsRepository()
    job = repository.create_job(
        {
            "job_code": "TCP-JOB-1",
            "operation_type": "outbound",
            "priority": "normal",
            "context": {},
            "steps": [
                {
                    "step_no": 1,
                    "action_type": "navigate",
                    "executor_type": "mobile",
                    "target_location_id": 12,
                    "input": {"waypoint": "PACK-01"},
                }
            ],
        }
    )
    step_id = job["steps"][0]["job_step_id"]
    repository.record_rmf_acceptance(step_id, "rmf-task-10-31", "PK_01")
    context = repository.claim_command(
        "rmf-task-10-31",
        {
            "robot_id": "PK_01",
            "execution_id": "execution-1",
            "map_revision": "warehouse:abc123",
        },
    )["task_context"]
    robot_status = status(sequence=9, task_context=context)
    repository.ingest_robot_status(robot_status)
    started = {
        "type": "task_event",
        "schema_version": 3,
        "event_id": str(uuid.uuid4()),
        "robot_id": "PK_01",
        "session_id": SESSION_ID,
        "event_type": "started",
        "reason_code": "COMMAND_ACCEPTED",
        "method_code": "NAV2_DEFAULT",
        "detail": "started",
        "task_context": context,
    }
    event = {**started, "event_id": str(uuid.uuid4()), "event_type": "arrived",
             "reason_code": "WAYPOINT_REACHED", "detail": "arrived"}

    repository.ingest_task_event(started)
    terminal_status = status(
        sequence=10,
        task_context=context,
        navigation_state=2,
        twist={"linear_x_mps": 0.0, "angular_z_rps": 0.0},
    )
    repository.ingest_robot_status(terminal_status)
    first = repository.ingest_task_event(event)
    repeated = repository.ingest_task_event(event)

    assert repository.get_device_state("PK_01")["details"]["sequence"] == 10
    assert first == repeated
    assert repository.get_job(1)["steps"][0]["state"] == "succeeded"
    assert [row["event_type"] for row in repository.get_job_timeline(1)] == [
        "job.created",
        "navigation.segment.started",
        "navigation.waypoint.arrived",
    ]


def test_terminal_event_requires_exact_command_map_session_and_status():
    repository = InMemoryFmsRepository()
    job = repository.create_job(
        {
            "job_code": "TCP-JOB-FENCE",
            "operation_type": "outbound",
            "priority": "normal",
            "context": {},
            "steps": [{
                "step_no": 10,
                "action_type": "navigate",
                "executor_type": "mobile",
                "target_location_id": 12,
                "input": {"waypoint": "대기1"},
            }],
        }
    )
    step_id = job["steps"][0]["job_step_id"]
    repository.record_rmf_acceptance(step_id, "rmf-task-fenced", "PK_01")
    context = repository.claim_command(
        "rmf-task-fenced",
        {
            "robot_id": "PK_01",
            "execution_id": "execution-fenced",
            "map_revision": "project1:abc123",
        },
    )["task_context"]
    repository.ingest_robot_status(status(sequence=11, task_context=context))
    forged_context = dict(context)
    forged_context["command_id"] = str(uuid.uuid4())
    forged_event = {
        "event_id": str(uuid.uuid4()),
        "robot_id": "PK_01",
        "session_id": SESSION_ID,
        "event_type": "arrived",
        "reason_code": "WAYPOINT_REACHED",
        "method_code": "NAV2_DEFAULT",
        "detail": "forged",
        "task_context": forged_context,
    }

    with pytest.raises(RuntimeContextConflict):
        repository.ingest_task_event(forged_event)
    assert repository.get_job(1)["steps"][0]["state"] == "pending"


def test_terminal_state_cannot_be_reopened_by_late_event():
    repository = InMemoryFmsRepository()
    job = repository.create_job(
        {
            "job_code": "TCP-JOB-TERMINAL",
            "operation_type": "outbound",
            "priority": "normal",
            "context": {},
            "steps": [{
                "step_no": 10,
                "action_type": "navigate",
                "executor_type": "mobile",
                "target_location_id": 12,
                "input": {"waypoint": "대기1"},
            }],
        }
    )
    step_id = job["steps"][0]["job_step_id"]
    repository.record_step_outcome(step_id, "failed")
    late = {
        "event_id": str(uuid.uuid4()),
        "robot_id": "PK_01",
        "session_id": SESSION_ID,
        "event_type": "started",
        "reason_code": "COMMAND_ACCEPTED",
        "method_code": "NAV2_DEFAULT",
        "detail": "late",
        "task_context": {
            "active": True,
            "job_id": 1,
            "job_step_id": step_id,
            "assignment_revision": 0,
            "rmf_task_id": "",
            "command_id": str(uuid.uuid4()),
            "map_revision": "project1:abc123",
            "command_source": "rmf",
        },
    }

    with pytest.raises(RuntimeContextConflict):
        repository.ingest_task_event(late)
    assert repository.get_job(1)["steps"][0]["state"] == "failed"


def test_prestart_failed_event_finishes_claimed_attempt_without_fake_started():
    repository = InMemoryFmsRepository()
    job = repository.create_job(
        {
            "job_code": "TCP-PRESTART-FAIL",
            "operation_type": "outbound",
            "priority": "normal",
            "context": {},
            "steps": [{
                "step_no": 10, "action_type": "navigate",
                "executor_type": "mobile", "target_location_id": 12,
                "input": {"waypoint": "대기1"},
            }],
        }
    )
    step_id = job["steps"][0]["job_step_id"]
    repository.record_rmf_acceptance(step_id, "rmf-prestart", "PK_01")
    context = repository.claim_command(
        "rmf-prestart",
        {"robot_id": "PK_01", "execution_id": "prestart", "map_revision": "project1:abc"},
    )["task_context"]
    repository.ingest_robot_status(status(
        sequence=12, task_context=context, navigation_state=4,
        map_revision="project1:abc",
    ))
    failed = {
        "event_id": str(uuid.uuid4()), "robot_id": "PK_01",
        "session_id": SESSION_ID, "event_type": "failed",
        "reason_code": "SENSOR_TELEMETRY_STALE", "method_code": "NAV2_DEFAULT",
        "detail": "not ready", "task_context": context,
    }

    repository.ingest_task_event(failed)

    assert repository.get_job(1)["steps"][0]["state"] == "failed"


def test_arrived_with_active_motion_facts_does_not_succeed():
    repository = InMemoryFmsRepository()
    job = repository.create_job(
        {
            "job_code": "TCP-BAD-ARRIVAL", "operation_type": "outbound",
            "priority": "normal", "context": {},
            "steps": [{"step_no": 10, "action_type": "navigate", "executor_type": "mobile",
                       "target_location_id": 12, "input": {"waypoint": "대기1"}}],
        }
    )
    step_id = job["steps"][0]["job_step_id"]
    repository.record_rmf_acceptance(step_id, "rmf-active", "PK_01")
    context = repository.claim_command(
        "rmf-active",
        {"robot_id": "PK_01", "execution_id": "active", "map_revision": "project1:abc"},
    )["task_context"]
    repository.ingest_task_event({
        "event_id": str(uuid.uuid4()), "robot_id": "PK_01", "session_id": SESSION_ID,
        "event_type": "started", "reason_code": "COMMAND_ACCEPTED",
        "method_code": "NAV2_DEFAULT", "detail": "started", "task_context": context,
    })
    repository.ingest_robot_status(status(
        sequence=13, task_context=context, navigation_state=1,
        map_revision="project1:abc",
    ))

    repository.ingest_task_event({
        "event_id": str(uuid.uuid4()), "robot_id": "PK_01", "session_id": SESSION_ID,
        "event_type": "arrived", "reason_code": "WAYPOINT_REACHED",
        "method_code": "NAV2_DEFAULT", "detail": "false arrival", "task_context": context,
    })

    assert repository.get_job(1)["steps"][0]["state"] == "failed"
