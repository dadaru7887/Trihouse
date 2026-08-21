from pathlib import Path
from xml.etree import ElementTree

import pytest
from rosidl_adapter.parser import (
    parse_action_file,
    parse_message_file,
    parse_service_file,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]

MESSAGE_FILES = {
    "BatteryActionDecision.msg",
    "BatteryCondition.msg",
    "BatteryPolicyState.msg",
    "ConnectionState.msg",
    "HandoverState.msg",
    "IndicatorState.msg",
    "KeepOutZone.msg",
    "MarkerObservation.msg",
    "NavigationState.msg",
    "ObjectDetection.msg",
    "PersonDetection.msg",
    "Readiness.msg",
    "RobotHealth.msg",
    "RobotStatus.msg",
    "SafetyState.msg",
    "StreamHealth.msg",
    "TaskContext.msg",
    "TaskEvent.msg",
}

SERVICE_FILES = {
    "ClearEmergency.srv",
    "EstimateTaskEnergy.srv",
}
ACTION_FILES = {"Dock.action", "ExecuteOmx.action", "ExecuteTransport.action"}

FORBIDDEN_OVER_SPLIT_FILES = {
    "TaskProgress.msg",
    "InferenceHealth.msg",
    "EmergencyAlert.msg",
    "GetLocation.srv",
}


def test_all_approved_interface_files_exist():
    assert {path.name for path in (PACKAGE_ROOT / "msg").glob("*.msg")} == MESSAGE_FILES
    assert {path.name for path in (PACKAGE_ROOT / "srv").glob("*.srv")} == SERVICE_FILES
    assert {path.name for path in (PACKAGE_ROOT / "action").glob("*.action")} == ACTION_FILES


@pytest.mark.parametrize("filename", sorted(MESSAGE_FILES))
def test_message_contract_is_valid_rosidl(filename):
    parsed = parse_message_file("trihouse_interfaces", PACKAGE_ROOT / "msg" / filename)
    assert parsed.base_type.type == filename.removesuffix(".msg")


@pytest.mark.parametrize("filename", sorted(SERVICE_FILES))
def test_service_contract_is_valid_rosidl(filename):
    parsed = parse_service_file("trihouse_interfaces", PACKAGE_ROOT / "srv" / filename)
    assert parsed.srv_name == filename.removesuffix(".srv")


@pytest.mark.parametrize("filename", sorted(ACTION_FILES))
def test_action_contract_is_valid_rosidl(filename):
    parsed = parse_action_file("trihouse_interfaces", PACKAGE_ROOT / "action" / filename)
    assert parsed.action_name == filename.removesuffix(".action")


def test_cmake_registers_every_interface():
    cmake = (PACKAGE_ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    expected = (
        {f'msg/{name}' for name in MESSAGE_FILES}
        | {f'srv/{name}' for name in SERVICE_FILES}
        | {f'action/{name}' for name in ACTION_FILES}
    )
    assert all(f'"{relative_path}"' in cmake for relative_path in expected)


def test_rejected_over_split_contracts_are_not_created():
    existing = {
        path.name
        for folder in ("msg", "srv", "action")
        for path in (PACKAGE_ROOT / folder).glob("*")
        if path.is_file()
    }
    assert existing.isdisjoint(FORBIDDEN_OVER_SPLIT_FILES)


def test_package_declares_rosidl_adapter_for_contract_tests():
    package_xml = ElementTree.parse(PACKAGE_ROOT / "package.xml").getroot()
    test_dependencies = {
        dependency.text for dependency in package_xml.findall("test_depend")
    }
    assert "rosidl_adapter" in test_dependencies


def test_battery_interfaces_keep_observation_policy_and_action_separate():
    battery_condition = (PACKAGE_ROOT / "msg" / "BatteryCondition.msg").read_text(
        encoding="utf-8"
    )
    battery_policy = (PACKAGE_ROOT / "msg" / "BatteryPolicyState.msg").read_text(
        encoding="utf-8"
    )
    action_decision = (
        PACKAGE_ROOT / "msg" / "BatteryActionDecision.msg"
    ).read_text(encoding="utf-8")
    estimate_service = (
        PACKAGE_ROOT / "srv" / "EstimateTaskEnergy.srv"
    ).read_text(encoding="utf-8")
    robot_status = (PACKAGE_ROOT / "msg" / "RobotStatus.msg").read_text(
        encoding="utf-8"
    )

    assert "float32 percentage" in battery_condition
    assert "bool present" in battery_condition
    assert "uint8 power_supply_status" in battery_condition
    assert "bool measurement_valid" in battery_condition
    assert "bool has_valid_sample" in battery_condition
    assert "bool telemetry_fresh" in battery_condition

    assert "uint8 STATE_LOCAL_ONLY=2" in battery_policy
    assert "trihouse_interfaces/BatteryCondition condition" in battery_policy
    assert "bool ready" in battery_policy
    assert "string reason_code" in battery_policy
    assert "string detail" in battery_policy

    assert "uint8 ACTION_RETURN_TO_CHARGE=5" in action_decision
    assert "float64 estimated_duration_s" in action_decision
    assert "float64 finish_state_of_charge" in action_decision

    assert "string[] waypoint_ids" in estimate_service
    assert "float64 finish_state_of_charge" in estimate_service
    assert "trihouse_interfaces/BatteryPolicyState battery_policy" in robot_status


def test_task_context_is_the_single_execution_identity_contract():
    task_context = (PACKAGE_ROOT / "msg" / "TaskContext.msg").read_text(
        encoding="utf-8"
    )
    assert task_context.splitlines() == [
        "bool active",
        "uint64 job_id",
        "uint64 job_step_id",
        "uint64 assignment_revision",
        "string rmf_task_id",
        "string command_id",
        "string map_revision",
        "string command_source",
    ]

    execute_transport = (
        PACKAGE_ROOT / "action" / "ExecuteTransport.action"
    ).read_text(encoding="utf-8").split("---", 1)[0]
    navigation_state = (
        PACKAGE_ROOT / "msg" / "NavigationState.msg"
    ).read_text(encoding="utf-8")
    task_event = (PACKAGE_ROOT / "msg" / "TaskEvent.msg").read_text(
        encoding="utf-8"
    )
    robot_status = (PACKAGE_ROOT / "msg" / "RobotStatus.msg").read_text(
        encoding="utf-8"
    )

    for contract in (execute_transport, navigation_state, task_event, robot_status):
        assert "trihouse_interfaces/TaskContext task_context" in contract

    assert "string command_id" not in execute_transport
    assert "string job_id" not in execute_transport
    assert "string job_step_id" not in execute_transport
    assert "string goal_id" not in navigation_state
    assert "string goal_id" not in task_event
    assert "string reason_code" in task_event
    assert "string method_code" in task_event


def test_robot_status_exposes_layered_readiness_and_map_revision():
    robot_status = (PACKAGE_ROOT / "msg" / "RobotStatus.msg").read_text(
        encoding="utf-8"
    )
    for field in (
        "string map_revision",
        "bool telemetry_valid",
        "bool execution_ready",
        "bool dispatchable",
        "bool ready",
    ):
        assert field in robot_status


def test_execute_omx_carries_versioned_json_without_duplicating_domain_fields():
    contract = (PACKAGE_ROOT / "action" / "ExecuteOmx.action").read_text(
        encoding="utf-8"
    )

    goal, result, feedback = [section.strip().splitlines() for section in contract.split("---")]
    assert goal == ["string command_json"]
    assert result == [
        "uint16 CODE_OK=0",
        "uint16 CODE_INVALID_COMMAND=1",
        "uint16 CODE_DEVICE_MISMATCH=2",
        "uint16 CODE_NOT_READY=3",
        "uint16 CODE_EXECUTION_FAILED=4",
        "bool success",
        "uint16 code",
        "string result_json",
    ]
    assert feedback == ["string event_json"]
