"""RobotStatus가 배터리 정책 메시지를 타입 그대로 보존하는 회귀 테스트."""

import rclpy

from trihouse_interfaces.msg import BatteryCondition, BatteryPolicyState, RobotStatus
from trihouse_pinky_fleet.gateway_node import build_robot_status_payload
from trihouse_pinky_fleet.status_node import StatusNode


def test_robot_status_build_message_preserves_battery_policy_message():
    if not rclpy.ok():
        rclpy.init()
    node = StatusNode()
    try:
        policy = BatteryPolicyState()
        policy.robot_id = "PK-01"
        node.battery = 18.0
        node.battery_policy = policy

        message = node._build_message()

        assert message.battery_percentage == 18.0
        assert isinstance(message.battery_policy, BatteryPolicyState)
        assert message.battery_policy.robot_id == "PK-01"
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
        condition.robot_id = "PK-01"
        condition.percentage = 18.0
        condition.present = True
        condition.measurement_valid = True
        condition.has_valid_sample = True
        condition.telemetry_fresh = True

        node._battery_condition(condition)
        message = node._build_message()

        assert message.battery_policy.condition.robot_id == "PK-01"
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
    message.robot_id = "PK-01"
    message.current_job_id = "job-7"
    message.current_job_step_id = "TRANSPORT"
    message.ready = True
    message.battery_percentage = 18.0
    message.battery_policy.condition.percentage = 18.0
    message.battery_policy.condition.present = True
    message.battery_policy.condition.measurement_valid = True
    message.battery_policy.condition.has_valid_sample = True
    message.battery_policy.condition.telemetry_fresh = True
    message.battery_policy.state = BatteryPolicyState.STATE_LOCAL_ONLY
    message.battery_policy.ready = True
    message.battery_policy.reason_code = "BATTERY_LOCAL_WORK_ONLY"

    payload = build_robot_status_payload(message, sent_at_ns=123)

    assert payload["sent_at_ns"] == 123
    assert payload["job_id"] == "job-7"
    assert payload["battery_condition"]["percentage"] == 18.0
    assert payload["battery_policy"]["state"] == BatteryPolicyState.STATE_LOCAL_ONLY
    assert payload["battery_policy"]["reason_code"] == "BATTERY_LOCAL_WORK_ONLY"
