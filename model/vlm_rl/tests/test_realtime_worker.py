import pytest
from model.vlm_rl.inference.navigation_context import GatewayNavigationContextSource, NavigationContext
from model.vlm_rl.inference.worker import DetectionEvidence, RecoveryInferenceWorker


class FakeVlm:
    model_name = "Qwen/Qwen2.5-VL-7B-Instruct"
    model_revision = "approved"

    def interpret(self, frame, detections, goal_text):
        return {
            "observations": [
                {
                    "region_id": "person-1",
                    "bbox_norm": [0.2, 0.2, 0.4, 0.8],
                    "semantic_label": "person",
                    "risk": "critical",
                    "confidence": 0.91,
                    "motion_evidence": "none",
                }
            ],
            "robot_candidate_sectors": [{"angle_deg": 20, "width_deg": 20, "preference": 0.8}],
            "uncertainty": 0.15,
        }


class FakePolicy:
    policy_name = "TGRPO+SAC"
    checkpoint_sha256 = "c" * 64

    def select(self, state):
        return 1, (0.1, 0.1, 0.0)


class RecordingProposalClient:
    def __init__(self):
        self.payloads = []

    def create(self, payload):
        self.payloads.append(payload)
        return {"status": "pending", "proposal_id": payload["proposal_id"]}


def context(**overrides):
    values = {
        "device_id": "PK_01",
        "map_name": "new_map_2",
        "map_revision": "new_map_2-r1",
        "robot_pose": (1.0, 2.0, 0.0),
        "goal_pose": (3.0, 4.0),
        "navigation_state": "stuck",
        "stuck_seconds": 4.0,
    }
    values.update(overrides)
    return NavigationContext(**values)


def detections():
    return [
        DetectionEvidence("person", 0.91, (0.2, 0.2, 0.4, 0.8), "track-1"),
        DetectionEvidence("obstacle", 0.70, (0.6, 0.3, 0.9, 0.9), "track-2"),
    ]


def test_worker_triggers_only_when_navigation_is_undecidable_with_evidence() -> None:
    client = RecordingProposalClient()
    worker = RecoveryInferenceWorker(FakeVlm(), FakePolicy(), client)

    assert worker.process(object(), detections(), context(navigation_state="navigating", stuck_seconds=0.2)) is None
    assert worker.process(object(), [], context()) is None
    assert client.payloads == []


def test_worker_preserves_all_detections_but_uses_one_worst_risk_state() -> None:
    client = RecordingProposalClient()
    worker = RecoveryInferenceWorker(FakeVlm(), FakePolicy(), client)

    result = worker.process(object(), detections(), context())

    assert result["status"] == "pending"
    proposal = client.payloads[0]
    assert len(proposal["perception_evidence"]) == 2
    assert proposal["state"]["risk_bbox_center_x_norm"] == pytest.approx(0.3)
    assert proposal["state"]["risk_bbox_center_y_norm"] == pytest.approx(0.5)
    assert proposal["state"]["risk_confidence"] == 0.91
    assert proposal["state"]["vlm_uncertainty"] == 0.15
    assert proposal["selected_skill_id"] == 1
    assert proposal["selected_skill_name"] == "REROUTE_LEFT"


def test_worker_rejects_invalid_vlm_contract_without_sending_a_proposal() -> None:
    class InvalidVlm(FakeVlm):
        def interpret(self, frame, detections, goal_text):
            return {"observations": "not-a-list", "uncertainty": 0.1}

    client = RecordingProposalClient()
    worker = RecoveryInferenceWorker(InvalidVlm(), FakePolicy(), client)

    assert worker.process(object(), detections(), context()) is None
    assert client.payloads == []


def test_worker_preserves_original_three_by_two_candidate_group() -> None:
    class GroupPolicy(FakePolicy):
        def select_group(self, state, *, k, m):
            assert (k, m) == (3, 2)
            return [
                (1, (0.1, 0.1, 0.0), -0.2),
                (2, (0.1, -0.1, 0.0), -0.2),
            ] * 3

    client = RecordingProposalClient()
    worker = RecoveryInferenceWorker(FakeVlm(), GroupPolicy(), client)

    worker.process(object(), detections(), context())

    candidates = client.payloads[0]["candidate_evidence"]
    assert len(candidates) == 6
    assert {item["skill_name"] for item in candidates} == {
        "REROUTE_LEFT", "REROUTE_RIGHT"
    }


def test_navigation_source_marks_no_progress_as_stuck_without_robot_self_judgement() -> None:
    replies = [{
        "device_id": "PK_01", "map_name": "new_map_2", "map_revision": "new_map_2-r1",
        "robot_pose": [1.0, 2.0, 0.0], "goal_pose": [3.0, 4.0],
        "navigation_state": "navigating", "observed_at": "2026-08-22T12:00:00+09:00",
    }] * 2
    times = iter((10.0, 14.5))
    source = GatewayNavigationContextSource(
        "http://gateway", "PK_01", transport=lambda _: replies.pop(0), clock=lambda: next(times)
    )

    assert source.get().stuck_seconds == 0.0
    second = source.get()
    assert second.stuck_seconds == 4.5
    assert second.navigation_state == "stuck"
