from copy import deepcopy

import pytest
from pydantic import ValidationError

from fms_gateway.app.recovery_models import RecoveryProposalCreate
from fms_gateway.app.recovery_repository import (
    InMemoryRecoveryRepository,
    RecoveryApprovalForbidden,
    RecoveryProposalConflict,
)


PROPOSAL_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
EPISODE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def proposal_payload() -> dict:
    return {
        "proposal_id": PROPOSAL_ID,
        "recovery_episode_uuid": EPISODE_ID,
        "step_no": 1,
        "device_id": "PK_01",
        "map_name": "new_map_2",
        "map_revision": "new_map_2-r1",
        "trigger_type": "blocked",
        "state_schema_id": "trihouse.recovery-state.v1",
        "state": {
            "robot_x_m": 1.0,
            "robot_y_m": 2.0,
            "robot_yaw_rad": 0.0,
            "goal_x_m": 3.0,
            "goal_y_m": 4.0,
            "risk_bbox_center_x_norm": 0.4,
            "risk_bbox_center_y_norm": 0.5,
            "risk_confidence": 0.9,
            "vlm_uncertainty": 0.1,
        },
        "perception_evidence": [
            {"class_name": "person", "confidence": 0.9, "bbox_xyxy_norm": [0.3, 0.2, 0.5, 0.8]},
            {"class_name": "obstacle", "confidence": 0.7, "bbox_xyxy_norm": [0.6, 0.4, 0.8, 0.9]},
        ],
        "vlm_lineage": {"model": "Qwen2.5-VL-7B-Instruct", "revision": "approved"},
        "policy_lineage": {"model": "TGRPO+SAC", "checkpoint_sha256": "c" * 64},
        "selected_skill_id": 1,
        "selected_skill_name": "REROUTE_LEFT",
        "selected_coord": [0.1, 0.1, 0.0],
        "safety_gate_enabled": True,
    }


def repository() -> InMemoryRecoveryRepository:
    return InMemoryRecoveryRepository(
        worker_roles={
            "W-CONTROL-01": "safety_manager",
            "W-WORKER-01": "operator",
        }
    )


def test_proposal_preserves_all_evidence_and_canonicalizes_selected_motion() -> None:
    repo = repository()
    request = RecoveryProposalCreate.model_validate(proposal_payload()).model_dump(mode="json")

    created = repo.create_proposal(request, "proposal-message-1", "a" * 64)

    assert created["status"] == "pending"
    assert created["action_family"] == "detour"
    assert created["selected_skill_id"] == 1
    assert created["selected_skill_name"] == "REROUTE_LEFT"
    assert created["canonical_action"]["heading_rad"] == pytest.approx(0.7853981634)
    assert len(repo.proposals[PROPOSAL_ID]["perception_evidence"]) == 2
    assert len(created["proposal_sha256"]) == 64


def test_proposal_rejects_a_raw_vector_or_wrong_skill_name() -> None:
    raw_state = proposal_payload()
    raw_state["state"] = [0.0] * 9
    with pytest.raises(ValidationError):
        RecoveryProposalCreate.model_validate(raw_state)

    wrong_skill = proposal_payload()
    wrong_skill["selected_skill_name"] = "REROUTE_RIGHT"
    with pytest.raises(ValidationError, match="skill"):
        RecoveryProposalCreate.model_validate(wrong_skill)


def test_only_safety_manager_can_approve_and_approval_creates_one_device_command() -> None:
    repo = repository()
    request = RecoveryProposalCreate.model_validate(proposal_payload()).model_dump(mode="json")
    created = repo.create_proposal(request, "proposal-message-1", "a" * 64)

    with pytest.raises(RecoveryApprovalForbidden):
        repo.decide_proposal(PROPOSAL_ID, "W-WORKER-01", "approved", "unsafe role")

    approved = repo.decide_proposal(PROPOSAL_ID, "W-CONTROL-01", "approved", "path clear")
    repeated = repo.decide_proposal(PROPOSAL_ID, "W-CONTROL-01", "approved", "path clear")

    assert repeated == approved
    assert approved["proposal_sha256"] == created["proposal_sha256"]
    assert approved["command"]["device_id"] == "PK_01"
    assert approved["command"]["selected_skill_name"] == "REROUTE_LEFT"
    assert len(repo.command_outbox) == 1


def test_decision_cannot_change_after_it_is_recorded() -> None:
    repo = repository()
    request = RecoveryProposalCreate.model_validate(proposal_payload()).model_dump(mode="json")
    repo.create_proposal(request, "proposal-message-1", "a" * 64)
    repo.decide_proposal(PROPOSAL_ID, "W-CONTROL-01", "rejected", "person too close")

    with pytest.raises(RecoveryProposalConflict):
        repo.decide_proposal(PROPOSAL_ID, "W-CONTROL-01", "approved", "changed mind")
    assert repo.command_outbox == []


def test_same_proposal_identity_cannot_be_reused_with_different_content() -> None:
    repo = repository()
    request = RecoveryProposalCreate.model_validate(proposal_payload()).model_dump(mode="json")
    repo.create_proposal(request, "proposal-message-1", "a" * 64)
    changed = deepcopy(request)
    changed["selected_coord"] = [0.05, 0.05, 0.0]

    with pytest.raises(RecoveryProposalConflict):
        repo.create_proposal(changed, "proposal-message-2", "b" * 64)
