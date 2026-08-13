"""RobotStatus가 배터리 정책 메시지를 타입 그대로 보존하는 회귀 테스트."""

from pathlib import Path

import pytest
import rclpy

from trihouse_interfaces.msg import (
    BatteryCondition, BatteryPolicyState, NavigationState, RobotStatus,
    TaskEvent,
)
from trihouse_pinky_fleet.gateway_node import (
    _event_required_navigation_state,
    _status_evidence_is_current,
    _with_replay_sequence,
    build_robot_status_payload, build_task_event_payload,
)
from trihouse_pinky_fleet.status_node import StatusNode
from trihouse_pinky_fleet.fleet_node import transport_admission_block_reason


def test_terminal_navigation_is_followed_by_inactive_idle_snapshot():
    if not rclpy.ok():
        rclpy.init()
    node = StatusNode()
    try:
        terminal = NavigationState()
        terminal.state = NavigationState.STATE_SUCCEEDED
        terminal.task_context.active = True
        terminal.task_context.job_id = 7
        terminal.task_context.job_step_id = 10

        node._navigation(terminal)

        assert node.navigation_state == NavigationState.STATE_IDLE
        assert node.task_context.active is False
        assert node.task_context.job_step_id == 0
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def test_robot_status_build_message_preserves_battery_policy_message():
    if not rclpy.ok():
        rclpy.init()
    node = StatusNode()
    try:
        policy = BatteryPolicyState()
        policy.robot_id = "PK_01"
        node.battery = 18.0
        node.battery_policy = policy

        message = node._build_message()

        assert message.battery_percentage == 18.0
        assert isinstance(message.battery_policy, BatteryPolicyState)
        assert message.battery_policy.robot_id == "PK_01"
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def test_robot_status_embeds_latest_validated_battery_condition():
    if not rclpy.ok():
        rclpy.init()
    node = StatusNode()
    try:
        condition = BatteryCondition()
        condition.robot_id = "PK_01"
        condition.percentage = 18.0
        condition.present = True
        condition.measurement_valid = True
        condition.has_valid_sample = True
        condition.telemetry_fresh = True

        node._battery_condition(condition)
        message = node._build_message()

        assert message.battery_policy.condition.robot_id == "PK_01"
        assert message.battery_policy.condition.percentage == 18.0
        assert message.battery_policy.condition.telemetry_fresh is True
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def test_gateway_source_serializes_structured_battery_contract():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "trihouse_pinky_fleet"
        / "trihouse_pinky_fleet"
        / "gateway_node.py"
    ).read_text(encoding="utf-8")
    assert "'battery_condition':" in source
    assert "'battery_policy':" in source
    assert "reason_code" in source


def test_gateway_payload_is_reusable_for_network_and_measurement_log():
    message = RobotStatus()
    message.robot_id = "PK_01"
    message.map_revision = "map-7"
    message.task_context.active = True
    message.task_context.job_id = 7
    message.task_context.job_step_id = 10
    message.task_context.assignment_revision = 3
    message.task_context.rmf_task_id = "rmf-task-1"
    message.task_context.command_id = "cmd-1"
    message.task_context.map_revision = "map-7"
    message.task_context.command_source = "RMF_ADAPTER"
    message.telemetry_valid = True
    message.execution_ready = True
    message.dispatchable = True
    message.ready = True
    message.navigation_state = 1
    message.task_progress = 0.4
    message.pose.pose.position.x = 1.2
    message.pose.pose.position.y = 3.4
    message.pose.pose.orientation.z = 0.247403959
    message.pose.pose.orientation.w = 0.968912422
    message.twist.linear.x = 0.2
    message.twist.angular.z = 0.1
    message.battery_percentage = 18.0
    message.battery_policy.condition.percentage = 18.0
    message.battery_policy.condition.present = True
    message.battery_policy.condition.measurement_valid = True
    message.battery_policy.condition.has_valid_sample = True
    message.battery_policy.condition.telemetry_fresh = True
    message.battery_policy.state = BatteryPolicyState.STATE_LOCAL_ONLY
    message.battery_policy.ready = True
    message.battery_policy.reason_code = "BATTERY_LOCAL_WORK_ONLY"

    payload = build_robot_status_payload(
        message, sent_at_ns=123, session_id="session-1", sequence=9,
    )

    assert payload["schema_version"] == 3
    assert payload["sent_at_ns"] == 123
    assert payload["session_id"] == "session-1"
    assert payload["sequence"] == 9
    assert payload["task_context"]["job_id"] == 7
    assert payload["task_context"]["job_step_id"] == 10
    assert payload["task_context"]["assignment_revision"] == 3
    assert payload["telemetry_valid"] is True
    assert payload["execution_ready"] is True
    assert payload["dispatchable"] is True
    assert payload["pose"]["x"] == 1.2
    assert payload["pose"]["y"] == 3.4
    assert payload["pose"]["yaw"] == pytest.approx(0.5)
    assert payload["twist"] == {
        "linear_x_mps": 0.2, "angular_z_rps": 0.1,
    }
    assert payload["navigation_state"] == 1
    assert payload["task_progress"] == pytest.approx(0.4)
    assert payload["battery_condition"]["percentage"] == 18.0
    assert payload["battery_policy"]["state"] == BatteryPolicyState.STATE_LOCAL_ONLY
    assert payload["battery_policy"]["reason_code"] == "BATTERY_LOCAL_WORK_ONLY"


def test_gateway_task_event_uses_v3_session_and_wire_event_names():
    event = TaskEvent()
    event.event_id = "1747bf84-6597-4b2f-9a71-bf65539b2836"
    event.robot_id = "PK_01"
    event.task_context.active = True
    event.task_context.job_id = 7
    event.task_context.job_step_id = 10
    event.task_context.assignment_revision = 2
    event.task_context.rmf_task_id = "rmf-7"
    event.task_context.command_id = "8f93b06f-8e52-4ca7-9e59-c7835d51ea92"
    event.task_context.map_revision = "map-7"
    event.task_context.command_source = "rmf"
    event.event_type = TaskEvent.EVENT_ARRIVED
    event.reason_code = "WAYPOINT_REACHED"
    event.method_code = "NAV2_DEFAULT"
    event.detail = "arrived"

    payload = build_task_event_payload(event, session_id="session-1")

    assert payload["schema_version"] == 3
    assert payload["session_id"] == "session-1"
    assert payload["event_type"] == "arrived"
    assert payload["reason_code"] == "WAYPOINT_REACHED"


def test_task_event_requires_its_matching_navigation_state_ack():
    assert _event_required_navigation_state("started") == 1
    assert _event_required_navigation_state("arrived") == 2
    assert _event_required_navigation_state("canceled") == 3
    assert _event_required_navigation_state("failed") == 4
    assert _event_required_navigation_state("unknown") is None


def test_replayed_terminal_status_gets_a_fresh_monotonic_sequence():
    original = {"sequence": 3, "sent_at_ns": 10, "navigation_state": 2}

    replay = _with_replay_sequence(original, sequence=9, sent_at_ns=20)

    assert replay == {"sequence": 9, "sent_at_ns": 20, "navigation_state": 2}
    assert original["sequence"] == 3


def test_outbox_capacity_blocks_all_transport_action_sources():
    assert transport_admission_block_reason(False) == (
        "task event outbox capacity reached"
    )
    assert transport_admission_block_reason(True) is None


def test_historical_terminal_snapshot_cannot_pose_as_current_status():
    evidence = {"_runtime_id": "old", "_captured_monotonic": 10.0}
    assert not _status_evidence_is_current(
        evidence, runtime_id="new", now=10.1,
    )
    assert not _status_evidence_is_current(
        {**evidence, "_runtime_id": "same"}, runtime_id="same", now=12.0,
    )
    assert _status_evidence_is_current(
        {"_runtime_id": "same", "_captured_monotonic": 10.0},
        runtime_id="same", now=10.5,
    )


def test_gateway_keeps_status_observation_time_in_latest_cache():
    source = Path(
        "trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/gateway_node.py"
    ).read_text(encoding="utf-8")
    assert "self.latest_status_payloads[context] = decorated_payload" in source
    task_event_section = source.split("def _task_event", 1)[1].split(
        "def _flush_event_outbox", 1
    )[0]
    assert "'_captured_monotonic': monotonic()" not in task_event_section
