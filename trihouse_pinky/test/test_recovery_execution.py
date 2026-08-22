from types import SimpleNamespace
from pathlib import Path

from trihouse_pinky_fleet.recovery_execution import recovery_admission_block_reason


def goal(**overrides):
    values = {
        "command_id": "11111111-1111-4111-8111-111111111111",
        "proposal_id": "22222222-2222-4222-8222-222222222222",
        "proposal_sha256": "a" * 64,
        "approval_id": "33333333-3333-4333-8333-333333333333",
        "approval_worker_id": "W-CONTROL-01",
        "device_id": "PK_01",
        "map_name": "new_map_2",
        "map_revision": "new_map_2-r1",
        "recovery_episode_uuid": "44444444-4444-4444-8444-444444444444",
        "step_no": 1,
        "selected_skill_id": 1,
        "selected_skill_name": "REROUTE_LEFT",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_recovery_accepts_matching_approved_stationary_goal() -> None:
    assert recovery_admission_block_reason(
        goal(),
        robot_id="PK_01",
        map_revision="new_map_2-r1",
        ready=True,
        recovery_health_ok=True,
        safety_available=True,
        emergency=False,
        stationary=True,
        transport_active=False,
    ) is None


def test_recovery_rejects_wrong_device_stale_map_or_motion_race() -> None:
    common = {
        "robot_id": "PK_01",
        "map_revision": "new_map_2-r1",
        "ready": True,
        "recovery_health_ok": True,
        "safety_available": True,
        "emergency": False,
        "stationary": True,
        "transport_active": False,
    }
    assert recovery_admission_block_reason(goal(device_id="PK_02"), **common) == "DEVICE_ID_MISMATCH"
    assert recovery_admission_block_reason(goal(map_revision="old"), **common) == "MAP_REVISION_MISMATCH"
    assert recovery_admission_block_reason(goal(), **{**common, "transport_active": True}) == "MOTION_BUSY"
    assert recovery_admission_block_reason(goal(), **{**common, "stationary": False}) == "ROBOT_NOT_STOPPED"


def test_recovery_rejects_unbound_approval_or_skill_pair() -> None:
    common = {
        "robot_id": "PK_01",
        "map_revision": "new_map_2-r1",
        "ready": True,
        "recovery_health_ok": True,
        "safety_available": True,
        "emergency": False,
        "stationary": True,
        "transport_active": False,
    }
    assert recovery_admission_block_reason(goal(proposal_sha256="bad"), **common) == "APPROVAL_INVALID"
    assert recovery_admission_block_reason(goal(approval_worker_id=""), **common) == "APPROVAL_INVALID"
    assert recovery_admission_block_reason(goal(selected_skill_name="REROUTE_RIGHT"), **common) == "SKILL_MISMATCH"


def test_recovery_fails_closed_without_safety_or_fresh_recovery_sensors() -> None:
    common = {
        "robot_id": "PK_01", "map_revision": "new_map_2-r1", "ready": True,
        "recovery_health_ok": True, "safety_available": True,
        "emergency": False, "stationary": True, "transport_active": False,
    }
    assert recovery_admission_block_reason(
        goal(), **{**common, "safety_available": False}
    ) == "SAFETY_SUPERVISOR_UNAVAILABLE"
    assert recovery_admission_block_reason(
        goal(), **{**common, "recovery_health_ok": False}
    ) == "RECOVERY_SENSOR_HEALTH_INVALID"


def test_fleet_recovery_uses_relative_nav2_actions_and_never_publishes_velocity() -> None:
    source = Path(
        "trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py"
    ).read_text(encoding="utf-8")

    assert "ExecuteRecovery" in source
    assert "'trihouse/recovery/execute'" in source
    assert "ActionClient(self, BackUp, 'backup')" in source
    assert "ActionClient(self, Spin, 'spin')" in source
    assert "ActionClient(self, DriveOnHeading, 'drive_on_heading')" in source
    assert "ActionClient(self, Wait, 'wait')" in source
    recovery_method = source.split("async def _execute_recovery", 1)[1].split("\n    def ", 1)[0]
    assert "create_publisher" not in recovery_method
    assert "cmd_vel" not in recovery_method
