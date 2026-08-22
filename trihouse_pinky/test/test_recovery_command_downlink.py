import pytest

from trihouse_pinky_fleet.protocol import ProtocolError, parse_recovery_command


def payload() -> dict:
    return {
        "type": "recovery_command",
        "schema_version": 1,
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
        "canonical_action": {
            "coord": [0.1, 0.1, 0.0],
            "map_target": None,
        },
    }


def test_recovery_command_keeps_approval_and_direction_identity() -> None:
    command = parse_recovery_command(payload())

    assert command.device_id == "PK_01"
    assert command.proposal_sha256 == "a" * 64
    assert command.selected_skill_id == 1
    assert command.selected_skill_name == "REROUTE_LEFT"
    assert command.canonical_coord == (0.1, 0.1, 0.0)


def test_recovery_command_rejects_skill_mismatch_and_unbounded_motion() -> None:
    mismatch = payload()
    mismatch["selected_skill_name"] = "REROUTE_RIGHT"
    with pytest.raises(ProtocolError, match="skill"):
        parse_recovery_command(mismatch)

    unbounded = payload()
    unbounded["canonical_action"]["coord"] = [1.0, 0.0, 0.0]
    with pytest.raises(ProtocolError, match="envelope"):
        parse_recovery_command(unbounded)
