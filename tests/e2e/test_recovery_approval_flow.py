import asyncio
import hashlib
import json

from fms_gateway.app.recovery_dispatch import dispatch_pending_once
from fms_gateway.app.recovery_export import iter_training_jsonl
from fms_gateway.app.recovery_models import RecoveryProposalCreate, RecoveryStepCompletion
from fms_gateway.app.recovery_repository import InMemoryRecoveryRepository
from model.vlm_rl.inference.completion_runtime import build_completion
from model.vlm_rl.inference.navigation_context import NavigationContext
from model.vlm_rl.inference.worker import DetectionEvidence, RecoveryInferenceWorker


class Vlm:
    model_name = "Qwen/Qwen2.5-VL-7B-Instruct"
    model_revision = "approved"

    def interpret(self, frame, detections, goal_text):
        return {
            "observations": [{
                "bbox_norm": [0.2, 0.2, 0.4, 0.8],
                "semantic_label": "person", "risk": "critical", "confidence": 0.9,
            }],
            "uncertainty": 0.1,
        }


class Policy:
    policy_name = "TGRPO+SAC"
    checkpoint_sha256 = "c" * 64

    def select(self, state):
        return 1, (0.1, 0.1, 0.0)


class RepositoryProposalClient:
    def __init__(self, repository):
        self.repository = repository
        self.proposal = None

    def create(self, payload):
        self.proposal = RecoveryProposalCreate.model_validate(payload).model_dump(mode="json")
        digest = hashlib.sha256(
            json.dumps(self.proposal, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return self.repository.create_proposal(self.proposal, payload["proposal_id"], digest)


class Links:
    def __init__(self):
        self.payload = None

    async def push(self, device_id, payload):
        assert device_id == "PK_01"
        self.payload = payload
        return True


def test_fake_perception_to_approved_action_to_one_training_row() -> None:
    repository = InMemoryRecoveryRepository()
    client = RepositoryProposalClient(repository)
    worker = RecoveryInferenceWorker(Vlm(), Policy(), client)
    context = NavigationContext(
        device_id="PK_01", map_name="new_map_2", map_revision="new_map_2-r1",
        robot_pose=(0.0, 0.0, 0.0), goal_pose=(1.0, 0.0),
        navigation_state="stuck", stuck_seconds=4.0,
    )
    created = worker.process(
        object(), [DetectionEvidence("person", 0.9, (0.2, 0.2, 0.4, 0.8))], context
    )
    proposal = created["_local_proposal"]
    approved = repository.decide_proposal(
        proposal["proposal_id"], "W-CONTROL-01", "approved", "supervised clear path"
    )
    links = Links()
    assert asyncio.run(dispatch_pending_once(repository, links)) == 1
    command = approved["command"]
    repository.record_command_ack("PK_01", {
        "command_id": command["command_id"],
        "proposal_sha256": command["proposal_sha256"],
        "accepted": True,
        "reason_code": "ACTION_ACCEPTED",
    })
    execution = {
        "command_id": command["command_id"],
        "proposal_sha256": command["proposal_sha256"],
        "success": True, "status": "succeeded", "terminal": True,
        "clearance_after_m": 0.5, "elapsed_seconds": 1.0,
        "safety_intervened": False,
    }
    repository.record_execution_result("PK_01", execution)
    completion = build_completion(
        proposal,
        repository.get_proposal_execution(proposal["proposal_id"])["result"],
        (0.2, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.2),
    )
    body = RecoveryStepCompletion.model_validate(completion).model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    repository.complete_recovery_step(
        proposal["recovery_episode_uuid"], proposal["step_no"], body,
        command["command_id"], digest,
    )

    rows = [json.loads(line) for line in iter_training_jsonl(repository.list_training_rows())]
    assert len(rows) == 1
    assert set(rows[0]) == {"state", "skill", "coord", "reward", "next_state", "done", "meta"}
    assert rows[0]["meta"]["is_execution"] is True
