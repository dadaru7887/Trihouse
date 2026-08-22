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


def test_recovery_command_ack_is_bound_to_the_session_device_and_proposal_hash():
    session = ProtocolSession(registered_robot_ids={"PK_01"})
    session.process(hello())
    command_id = str(uuid.uuid4())

    accepted = session.process(
        {
            "type": "recovery_command_ack",
            "schema_version": 3,
            "robot_id": "PK_01",
            "session_id": SESSION_ID,
            "command_id": command_id,
            "proposal_sha256": "a" * 64,
            "accepted": True,
            "reason_code": "ACTION_ACCEPTED",
        }
    )

    assert accepted.action == "recovery_command_ack"
    assert accepted.robot_id == "PK_01"
    assert accepted.payload["command_id"] == command_id


def test_recovery_command_ack_rejects_an_invalid_hash():
    session = ProtocolSession(registered_robot_ids={"PK_01"})
    session.process(hello())

    with pytest.raises(ProtocolRejected, match="SCHEMA_INVALID"):
        session.process(
            {
                "type": "recovery_command_ack",
                "schema_version": 3,
                "robot_id": "PK_01",
                "session_id": SESSION_ID,
                "command_id": str(uuid.uuid4()),
                "proposal_sha256": "not-a-hash",
                "accepted": False,
                "reason_code": "SAFETY_VETO",
            }
        )


def test_recovery_execution_result_is_bound_to_authenticated_robot() -> None:
    session = ProtocolSession({"PK_01"})
    session.process(hello())

    processed = session.process({
        "type": "recovery_execution_result",
        "schema_version": 3,
        "robot_id": "PK_01",
        "session_id": SESSION_ID,
        "command_id": "11111111-1111-4111-8111-111111111111",
        "proposal_sha256": "a" * 64,
        "success": True,
        "status": "succeeded",
        "detail": "completed",
        "pre_pose": {"x": 1.0, "y": 2.0, "yaw": 0.0},
        "post_pose": {"x": 1.1, "y": 2.0, "yaw": 0.1},
        "clearance_before_m": 0.4,
        "clearance_after_m": 0.5,
        "elapsed_seconds": 1.2,
        "safety_intervened": False,
        "terminal": True,
    })

    assert processed.action == "recovery_execution_result"
    assert processed.robot_id == "PK_01"


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
    # 거절 응답은 사유와 함께 **무엇이** 거절됐는지 싣는다. 로봇 쪽 로그가 모든
    # 거절을 한 문장으로 적기 때문에, 이것이 없으면 원인을 되짚을 수 없다.
    assert rejection == {
        "type": "event_rejected",
        "reason_code": "ROBOT_ID_MISMATCH",
        "message_type": "robot_status",
    }
    assert [message.action for message in accepted] == [
        "hello_accepted",
        "heartbeat",
        "robot_status",
        "task_event",
    ]


def test_rejection_names_the_offending_message_type_in_response_and_log(caplog):
    """거절이 **무엇을** 거절했는지 남기는지 확인한다.

    이것이 없던 동안 `MESSAGE_TYPE_UNSUPPORTED` 42건의 원인을 찾지 못했다. 로봇 쪽
    로그는 모든 거절을 같은 문장으로 적고, Gateway 는 아무것도 남기지 않았기 때문이다.

    같은 테스트가 두 후보를 구분한다. `session_id` 가 없는 메시지는 타입 판정에
    닿기 전에 `SESSION_ID_MISMATCH` 로 걸리므로, `command_ack` 는
    `MESSAGE_TYPE_UNSUPPORTED` 의 원인이 될 수 없다.
    """

    async def scenario():
        server = TcpIngestionServer(
            host="127.0.0.1",
            port=0,
            registered_robot_ids=lambda: {"PK_01"},
            on_message=lambda processed: None,
        )
        await server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
            writer.write((json.dumps(hello()) + "\n").encode())
            await writer.drain()
            await reader.readline()

            # session_id 를 싣지 않는 메시지 — 로봇의 command_ack 가 이 모양이다.
            writer.write(
                (json.dumps({"type": "command_ack", "robot_id": "PK_01"}) + "\n").encode()
            )
            await writer.drain()
            without_session = json.loads(await reader.readline())

            # 신원은 온전하고 타입만 모르는 메시지.
            writer.write(
                (
                    json.dumps(
                        {
                            "type": "telemetry",
                            "schema_version": 3,
                            "robot_id": "PK_01",
                            "session_id": SESSION_ID,
                        }
                    )
                    + "\n"
                ).encode()
            )
            await writer.drain()
            unknown_type = json.loads(await reader.readline())

            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()
        return without_session, unknown_type

    with caplog.at_level("WARNING", logger="fms_gateway.app.tcp_protocol"):
        without_session, unknown_type = asyncio.run(scenario())

    assert without_session == {
        "type": "event_rejected",
        "reason_code": "SESSION_ID_MISMATCH",
        "message_type": "command_ack",
    }
    assert unknown_type == {
        "type": "event_rejected",
        "reason_code": "MESSAGE_TYPE_UNSUPPORTED",
        "message_type": "telemetry",
    }

    # 로그만 보고도 어느 로봇의 어떤 메시지가 걸렸는지 알 수 있어야 한다.
    rejected = [record.getMessage() for record in caplog.records]
    assert any("MESSAGE_TYPE_UNSUPPORTED" in line and "telemetry" in line for line in rejected)
    assert any("SESSION_ID_MISMATCH" in line and "command_ack" in line for line in rejected)
    assert all("PK_01" in line for line in rejected)


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


def test_arrival_is_judged_on_the_snapshot_the_robot_reported_at_arrival():
    """도착 뒤 다음 구간이 시작돼도 그 도착은 성립한다.

    ## 왜

    RMF 는 도착 보고 **18 ms 뒤**에 다음 구간을 지시한다(2026-08-19 실측).
    로봇이 다시 움직이기 시작하면 `device_states` 의 그 한 줄은 곧바로
    "주행중" 으로 덮인다. 도착 이벤트를 **살아 있는 최신 상태**로 판정하면,
    로봇이 제대로 도착했는데도 `navigation_state != 2` 라서 거절된다.

    실측에서 step 20 이 이렇게 죽었다 — 로봇은 두 구간을 다 정상 주행했고
    냉동창고 도착도 성공했는데, 원장은 도착 25 초 **전에** 이미
    `GOAL_TOLERANCE_NOT_MET` 으로 실패를 적었다. 로봇 쪽 정밀 정차 검사는
    한 번도 실패하지 않았다.

    로봇은 도착 순간의 스냅샷을 이벤트와 짝지어 보낸다
    (`event_outbox._compatible_status`). 판정은 그 증거를 봐야 한다.
    """
    repository = InMemoryFmsRepository()
    job = repository.create_job(
        {
            "job_code": "TCP-JOB-RACE",
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
    repository.record_rmf_acceptance(step_id, "rmf-task-race", "PK_01")
    context = repository.claim_command(
        "rmf-task-race",
        {
            "robot_id": "PK_01",
            "execution_id": "execution-race",
            "map_revision": "warehouse:abc123",
        },
    )["task_context"]

    repository.ingest_robot_status(status(sequence=9, task_context=context))
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
    repository.ingest_task_event(started)

    # 도착 — 로봇이 서고, 이 스냅샷이 도착의 증거가 된다.
    repository.ingest_robot_status(
        status(
            sequence=10,
            task_context=context,
            navigation_state=2,
            twist={"linear_x_mps": 0.0, "angular_z_rps": 0.0},
        )
    )
    # RMF 가 다음 구간을 지시해 로봇이 다시 움직인다. 도착 이벤트가 서버에
    # 닿기 전에 이 상태가 같은 줄을 덮는다.
    repository.ingest_robot_status(
        status(
            sequence=11,
            task_context=context,
            navigation_state=1,
            twist={"linear_x_mps": 0.18, "angular_z_rps": 0.0},
        )
    )

    arrived = {
        **started,
        "event_id": str(uuid.uuid4()),
        "event_type": "arrived",
        "reason_code": "WAYPOINT_REACHED",
        "detail": "arrived",
    }
    repository.ingest_task_event(arrived)

    assert repository.get_job(job["job_id"])["steps"][0]["state"] == "succeeded"


def _navigate_job(repository, *, target_location_id):
    job = repository.create_job(
        {
            "job_code": f"TCP-JOB-NAV-{target_location_id}",
            "operation_type": "outbound",
            "priority": "normal",
            "context": {},
            "steps": [
                {
                    "step_no": 1,
                    "action_type": "navigate",
                    "executor_type": "mobile",
                    "target_location_id": target_location_id,
                    "input": {},
                }
            ],
        }
    )
    step_id = job["steps"][0]["job_step_id"]
    rmf_task_id = f"rmf-nav-{target_location_id}"
    repository.record_rmf_acceptance(step_id, rmf_task_id, "PK_01")
    context = repository.claim_command(
        rmf_task_id,
        {
            "robot_id": "PK_01",
            "execution_id": f"execution-{target_location_id}",
            "map_revision": "warehouse:abc123",
        },
    )["task_context"]
    base = {
        "type": "task_event",
        "schema_version": 3,
        "robot_id": "PK_01",
        "session_id": SESSION_ID,
        "method_code": "NAV2_DEFAULT",
        "task_context": context,
    }
    repository.ingest_task_event({
        **base, "event_id": str(uuid.uuid4()), "event_type": "started",
        "reason_code": "COMMAND_ACCEPTED", "detail": "started",
    })
    return job, context, base


def _arrive_at(repository, base, context, *, x, y, sequence):
    repository.ingest_robot_status(
        status(
            sequence=sequence,
            task_context=context,
            navigation_state=2,
            pose={"x": x, "y": y, "yaw": 0.0},
            twist={"linear_x_mps": 0.0, "angular_z_rps": 0.0},
        )
    )
    return repository.ingest_task_event({
        **base, "event_id": str(uuid.uuid4()), "event_type": "arrived",
        "reason_code": "WAYPOINT_REACHED", "detail": "arrived",
    })


# 포장대 도크 하나만 있는 최소 지도. 좌표는 승인된 JSONL 의 실측값이다.
PACKING_DOCK = {
    "location_id": 28,
    "location_code": "PACKING-01-DOCK-01",
    "pose_x": 0.351,
    "pose_y": -0.490,
}
# 병목 01. 포장대까지 0.61 m 떨어져 있다.
BOTTLENECK_X, BOTTLENECK_Y = 0.841, -0.111


def test_a_waypoint_on_the_way_does_not_close_the_step() -> None:
    """RMF 는 한 이동을 구간마다 나눠 주고 로봇은 구간마다 `arrived` 를 낸다.

    2026-08-19 실측: 그 첫 신호로 단계가 닫혀, 병목에서 낸 도착이 포장대 도착으로
    기록됐다. 로봇은 물건을 실은 채 통로 한가운데 섰는데 원장에는 "인계 완료" 가
    남았다. 중간 지점의 도착은 **실패도 성공도 아니고 아직 끝나지 않은 것**이다.
    """
    repository = InMemoryFmsRepository(seed_locations=[PACKING_DOCK])
    job, context, base = _navigate_job(repository, target_location_id=28)

    result = _arrive_at(
        repository, base, context, x=BOTTLENECK_X, y=BOTTLENECK_Y, sequence=10
    )

    assert result["event_type"] == "navigation.waypoint.passed"
    assert repository.get_job(job["job_id"])["steps"][0]["state"] == "running"


def test_arriving_at_the_target_closes_the_step() -> None:
    repository = InMemoryFmsRepository(seed_locations=[PACKING_DOCK])
    job, context, base = _navigate_job(repository, target_location_id=28)

    result = _arrive_at(
        repository, base, context,
        x=PACKING_DOCK["pose_x"], y=PACKING_DOCK["pose_y"], sequence=10,
    )

    assert result["event_type"] == "navigation.waypoint.arrived"
    assert repository.get_job(job["job_id"])["steps"][0]["state"] == "succeeded"


def test_a_step_without_a_target_location_still_arrives() -> None:
    """복귀처럼 목표 좌표가 없는 단계는 비교할 것이 없다. 막으면 안 된다."""
    repository = InMemoryFmsRepository(seed_locations=[PACKING_DOCK])
    job, context, base = _navigate_job(repository, target_location_id=None)

    result = _arrive_at(repository, base, context, x=9.0, y=9.0, sequence=10)

    assert result["event_type"] == "navigation.waypoint.arrived"
    assert repository.get_job(job["job_id"])["steps"][0]["state"] == "succeeded"
