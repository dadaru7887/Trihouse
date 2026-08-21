"""FMS 없이 waypoint를 측정할 때도 안전 gate를 거치는 local-manual 계약."""

import sys
from pathlib import Path


PINKY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PINKY / "trihouse_pinky_safety"))
LOCAL_MANUAL_LAUNCH = (
    PINKY / "trihouse_pinky_bringup" / "launch" / "local_manual.launch.py"
)
BRINGUP_PACKAGE_XML = PINKY / "trihouse_pinky_bringup" / "package.xml"

from trihouse_pinky_safety.policy import MotionCommand, select_manual_command  # noqa: E402


def test_fresh_manual_command_is_selected() -> None:
    command = MotionCommand(0.06, -0.2)

    assert select_manual_command(
        command, now_s=10.20, received_at_s=10.0, timeout_s=0.25
    ) == command


def test_stale_manual_command_stops_the_robot() -> None:
    assert select_manual_command(
        MotionCommand(0.06, 0.0), now_s=10.26, received_at_s=10.0, timeout_s=0.25
    ) == MotionCommand(0.0, 0.0)


def test_local_manual_launch_keeps_safety_between_teleop_and_motor() -> None:
    source = LOCAL_MANUAL_LAUNCH.read_text(encoding="utf-8")

    assert "bringup_robot.launch.xml" in source
    assert "pinky_sensor_adc" in source
    assert "ultrasonic_adapter" in source
    assert "safety_supervisor" in source
    assert "'manual_mode_enabled': True" in source


def test_local_manual_launch_declares_its_runtime_dependencies() -> None:
    source = BRINGUP_PACKAGE_XML.read_text(encoding="utf-8")

    for package in (
        "pinky_bringup",
        "pinky_sensor_adc",
        "trihouse_pinky_io",
        "trihouse_pinky_safety",
    ):
        assert f"<exec_depend>{package}</exec_depend>" in source
