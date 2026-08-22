"""실제 Pinky로 창고 협로 규칙을 한 번씩 보정하는 hardware module test.

기본 pytest에서는 gate 계약만 실행하고 실제 scenario는 skip된다. 이 파일은 Twist를
발행하지 않으며, Fleet의 ExecuteTransport action을 통해서만 이동을 요청한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml


REPOSITORY = Path(__file__).resolve().parents[2]
PINKY = REPOSITORY / "trihouse_pinky"
sys.path.insert(0, str(PINKY / "trihouse_pinky_docking"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from trihouse_pinky_docking.narrow_zone import load_narrow_zones  # noqa: E402
from narrow_zone_client import (  # noqa: E402
    MotionRequest,
    PersistentTrace,
    PhysicalNarrowZoneClient,
    validate_motion_request,
)


PROFILE_FILE = REPOSITORY / "config" / "narrow_zones.new_map_2.yaml"
FROZEN = "frozen_storage_loading_dock_01"


def test_trace_event_is_persisted_before_the_motion_finishes(tmp_path) -> None:
    summary = tmp_path / "attempt.json"
    trace = PersistentTrace(
        summary,
        context={"robot_namespace": "pinky_01", "phase": "roundtrip"},
    )

    trace.record("goal_sent", destination_code=FROZEN, x=1.25, y=-0.5)

    events = [
        __import__("json").loads(line)
        for line in summary.with_suffix(".jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[0]["event"] == "attempt_started"
    assert events[1]["event"] == "goal_sent"
    assert events[1]["destination_code"] == FROZEN
    assert events[1]["x"] == 1.25
    assert events[1]["elapsed_s"] >= 0.0
    assert events[1]["timestamp"].endswith("Z")


def test_robot_status_records_the_map_pose_in_the_persistent_trace(tmp_path) -> None:
    from types import SimpleNamespace

    trace = PersistentTrace(tmp_path / "attempt.json", context={})
    client = PhysicalNarrowZoneClient.__new__(PhysicalNarrowZoneClient)
    client.map_revision = ""
    client.trace_recorder = trace
    message = SimpleNamespace(
        map_revision="trihouse_test_01:abc",
        frame_id="map",
        pose=SimpleNamespace(
            pose=SimpleNamespace(
                position=SimpleNamespace(x=1.2, y=-0.7),
                orientation=SimpleNamespace(x=0.0, y=0.0, z=0.5, w=0.8660254),
            )
        ),
    )

    client._on_status(message)

    event = __import__("json").loads(
        trace.event_path.read_text(encoding="utf-8").splitlines()[-1]
    )
    assert event["event"] == "pose"
    assert event["frame_id"] == "map"
    assert event["map_revision"] == "trihouse_test_01:abc"
    assert event["x"] == 1.2
    assert event["y"] == -0.7
    assert event["yaw"] == pytest.approx(1.0471976)


def _profiles():
    return load_narrow_zones(
        yaml.safe_load(PROFILE_FILE.read_text(encoding="utf-8")),
        map_name="new_map_2",
    )


def test_motion_is_disabled_without_an_explicit_flag() -> None:
    decision = validate_motion_request(
        MotionRequest(False, "pinky_01", FROZEN, "enter"), _profiles()
    )

    assert decision.allowed is False
    assert decision.reason_code == "MOTION_NOT_ENABLED"


@pytest.mark.parametrize("namespace", ["", "/", "pinky 01"])
def test_a_robot_namespace_is_required(namespace: str) -> None:
    decision = validate_motion_request(
        MotionRequest(True, namespace, FROZEN, "enter"), _profiles()
    )

    assert decision.allowed is False
    assert decision.reason_code == "ROBOT_NAMESPACE_INVALID"


def test_an_unknown_destination_is_rejected_before_ros_is_started() -> None:
    decision = validate_motion_request(
        MotionRequest(True, "pinky_01", "unknown_warehouse", "enter"), _profiles()
    )

    assert decision.allowed is False
    assert decision.reason_code == "NARROW_PROFILE_UNKNOWN"


def test_disabled_warehouse_cannot_be_used_for_calibration() -> None:
    decision = validate_motion_request(
        MotionRequest(
            True,
            "pinky_01",
            "ambient_storage_loading_dock_01",
            "enter",
        ),
        _profiles(),
    )

    assert decision.allowed is False
    assert decision.reason_code == "NARROW_CALIBRATION_NOT_READY"


@pytest.mark.parametrize("phase", ["enter", "exit", "roundtrip"])
def test_frozen_candidate_has_enough_structure_for_each_bounded_phase(phase: str) -> None:
    decision = validate_motion_request(
        MotionRequest(True, "pinky_01", FROZEN, phase), _profiles()
    )

    assert decision.allowed is True
    assert decision.profile == _profiles()[FROZEN]


@pytest.mark.hardware
def test_drive_one_narrow_zone_attempt(pytestconfig) -> None:
    request = MotionRequest(
        enable_motion=pytestconfig.getoption("--enable-motion"),
        robot_namespace=pytestconfig.getoption("--robot-namespace"),
        destination_code=pytestconfig.getoption("--destination"),
        phase=pytestconfig.getoption("--phase"),
    )
    decision = validate_motion_request(request, _profiles())
    if not request.enable_motion:
        pytest.skip("--enable-motion이 없어 실제 Pinky goal을 보내지 않는다")
    assert decision.allowed, f"{decision.reason_code}: {decision.reason}"

    client = PhysicalNarrowZoneClient(request, decision.profile)
    try:
        readiness = client.wait_for_motion_gate(timeout_s=10.0)
        assert readiness.allowed, f"{readiness.reason_code}: {readiness.reason}"
        result = client.execute_once(timeout_s=120.0)
    finally:
        client.close()

    assert result.success, f"{result.code}: {result.message}; trace={result.trace_path}"
