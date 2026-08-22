"""실물과 같은 ExecuteTransport 경계로 Gazebo 협로 왕복을 디버깅한다."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


REPOSITORY = Path(__file__).resolve().parents[2]
PINKY = REPOSITORY / "trihouse_pinky"
HARDWARE_TESTS = REPOSITORY / "tests" / "hardware"
sys.path.insert(0, str(PINKY / "trihouse_pinky_docking"))
sys.path.insert(0, str(HARDWARE_TESTS))

from trihouse_pinky_docking.narrow_zone import load_narrow_zones  # noqa: E402
import narrow_zone_client  # noqa: E402
from narrow_zone_client import MotionRequest, PhysicalNarrowZoneClient  # noqa: E402


PROFILE_FILE = REPOSITORY / "config" / "narrow_zones.new_map_2.yaml"
FROZEN = "frozen_storage_loading_dock_01"


def _profiles():
    return load_narrow_zones(
        yaml.safe_load(PROFILE_FILE.read_text(encoding="utf-8")),
        map_name="new_map_2",
    )


def _validate(request: MotionRequest, domain_id: str, calibration_enabled: bool):
    validator = getattr(narrow_zone_client, "validate_simulation_request", None)
    assert validator is not None, "simulation 전용 domain/calibration gate가 필요하다"
    return validator(
        request,
        _profiles(),
        ros_domain_id=domain_id,
        calibration_enabled=calibration_enabled,
    )


def test_simulation_rejects_the_physical_ros_domain() -> None:
    decision = _validate(
        MotionRequest(True, "pinky_01", FROZEN, "roundtrip"),
        domain_id="12",
        calibration_enabled=True,
    )

    assert decision.allowed is False
    assert decision.reason_code == "SIMULATION_DOMAIN_MISMATCH"


def test_simulation_rejects_an_unmeasured_profile_without_calibration() -> None:
    decision = _validate(
        MotionRequest(True, "pinky_01", FROZEN, "roundtrip"),
        domain_id="0",
        calibration_enabled=False,
    )

    assert decision.allowed is False
    assert decision.reason_code == "SIMULATION_CALIBRATION_DISABLED"


def test_simulation_accepts_one_explicitly_gated_roundtrip() -> None:
    decision = _validate(
        MotionRequest(True, "pinky_01", FROZEN, "roundtrip"),
        domain_id="0",
        calibration_enabled=True,
    )

    assert decision.allowed is True
    assert decision.profile == _profiles()[FROZEN]


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("Boolean value is: True\n", True),
        ("Boolean value is: False\n", False),
        ("Parameter not set\n", False),
    ],
)
def test_ros_parameter_output_must_explicitly_report_true(
    output: str, expected: bool
) -> None:
    parser = getattr(narrow_zone_client, "ros_boolean_parameter_is_true", None)
    assert parser is not None, "ros2 param get 결과를 엄격히 판정해야 한다"
    assert parser(output) is expected


@pytest.mark.simulation
def test_drive_one_simulated_narrow_zone_roundtrip(pytestconfig) -> None:
    enabled = pytestconfig.getoption("--enable-sim-motion")
    request = MotionRequest(
        enable_motion=enabled,
        robot_namespace=pytestconfig.getoption("--sim-robot-namespace"),
        destination_code=pytestconfig.getoption("--sim-destination"),
        phase=pytestconfig.getoption("--sim-phase"),
    )
    if not enabled:
        pytest.skip("--enable-sim-motion이 없어 Gazebo goal을 보내지 않는다")

    parameter = subprocess.run(
        [
            "ros2",
            "param",
            "get",
            f"/{request.robot_namespace}/trihouse_fleet",
            "allow_narrow_calibration",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    parser = getattr(narrow_zone_client, "ros_boolean_parameter_is_true", None)
    calibration_enabled = bool(
        parameter.returncode == 0 and parser is not None and parser(parameter.stdout)
    )
    decision = _validate(
        request,
        domain_id=os.environ.get("ROS_DOMAIN_ID", ""),
        calibration_enabled=calibration_enabled,
    )
    assert decision.allowed, f"{decision.reason_code}: {decision.reason}"

    client = PhysicalNarrowZoneClient(request, decision.profile)
    try:
        readiness = client.wait_for_motion_gate(timeout_s=10.0)
        assert readiness.allowed, f"{readiness.reason_code}: {readiness.reason}"
        result = client.execute_once(timeout_s=120.0)
    finally:
        client.close()

    assert result.success, f"{result.code}: {result.message}; trace={result.trace_path}"
