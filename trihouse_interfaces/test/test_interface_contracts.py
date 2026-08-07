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
    "BatteryPolicyState.msg",
    "CargoState.msg",
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
    "TaskEvent.msg",
}

SERVICE_FILES = {"ClearEmergency.srv", "SetCargoLock.srv"}
ACTION_FILES = {"Dock.action", "ExecuteTransport.action"}

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
