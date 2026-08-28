"""The Gateway must accept and validate distilled-selector evidence on a proposal."""

import pytest

pytest.importorskip("pydantic")

from fms_gateway.app.recovery_models import RecoveryProposalCreate


def proposal(**overrides):
    payload = {
        "proposal_id": "11111111-1111-4111-8111-111111111111",
        "recovery_episode_uuid": "22222222-2222-4222-8222-222222222222",
        "step_no": 1,
        "device_id": "PK_01",
        "map_name": "new_map_2",
        "map_revision": "new_map_2-r1",
        "trigger_type": "person",
        "state_schema_id": "trihouse.recovery-state.v1",
        "state": {
            "robot_x_m": 1.0, "robot_y_m": 2.0, "robot_yaw_rad": 0.0,
            "goal_x_m": 3.0, "goal_y_m": 4.0,
            "risk_bbox_center_x_norm": 0.3, "risk_bbox_center_y_norm": 0.5,
            "risk_confidence": 0.91, "vlm_uncertainty": 0.15,
        },
        "perception_evidence": [
            {"class_name": "person", "confidence": 0.91, "bbox_xyxy_norm": [0.2, 0.2, 0.4, 0.8]}
        ],
        "vlm_lineage": {"model": "Qwen/Qwen2.5-VL-7B-Instruct", "revision": "approved"},
        "policy_lineage": {"model": "TGRPO+SAC", "checkpoint_sha256": "c" * 64},
        "selected_skill_id": 2,
        "selected_skill_name": "REROUTE_RIGHT",
        "selected_coord": [0.1, -0.1, 0.0],
        "candidate_evidence": [],
        "safety_gate_enabled": True,
    }
    payload.update(overrides)
    return payload


def selection(**overrides):
    values = {
        "source": "distilled_ensemble",
        "use_learned": True,
        "entropy": 1.02,
        "unanimous": True,
        "mean_probs": [0.05, 0.15, 0.7, 0.05, 0.05],
        "reason": "entropy=1.02<=1.5, unanimous=True",
        "learned_skill_id": 2,
        "learned_skill_name": "REROUTE_RIGHT",
        "selector_lineage": {
            "model": "high-level-distilled-ensemble", "ensemble_sha256": "e" * 64,
        },
    }
    values.update(overrides)
    return values


def test_gateway_accepts_a_trusted_distilled_selection() -> None:
    model = RecoveryProposalCreate(**proposal(skill_selection=selection()))

    assert model.skill_selection.source == "distilled_ensemble"
    assert model.skill_selection.learned_skill_id == 2


def test_gateway_keeps_accepting_proposals_without_selector_evidence() -> None:
    model = RecoveryProposalCreate(**proposal())

    assert model.skill_selection is None


def test_gateway_rejects_a_learned_skill_name_that_contradicts_the_ontology() -> None:
    with pytest.raises(ValueError):
        RecoveryProposalCreate(**proposal(
            skill_selection=selection(learned_skill_id=2, learned_skill_name="BACKUP")
        ))


def test_gateway_rejects_a_trusted_selection_that_names_no_skill() -> None:
    with pytest.raises(ValueError):
        RecoveryProposalCreate(**proposal(
            skill_selection=selection(use_learned=True, learned_skill_id=None,
                                      learned_skill_name=None)
        ))


def test_gateway_rejects_a_non_finite_entropy() -> None:
    with pytest.raises(ValueError):
        RecoveryProposalCreate(**proposal(skill_selection=selection(entropy=float("nan"))))


def test_gateway_rejects_an_unknown_selection_source() -> None:
    with pytest.raises(ValueError):
        RecoveryProposalCreate(**proposal(skill_selection=selection(source="vibes")))


def _worker_payload(decision_kwargs, *, group_policy=True):
    """Drive the real inference worker and return the proposal it would POST."""
    from model.vlm_rl.inference.distilled_selector import SelectorDecision
    from model.vlm_rl.inference.navigation_context import NavigationContext
    from model.vlm_rl.inference.worker import DetectionEvidence, RecoveryInferenceWorker

    class Vlm:
        model_name, model_revision = "Qwen/Qwen2.5-VL-7B-Instruct", "approved"

        def interpret(self, frame, detections, goal_text):
            return {
                "observations": [{
                    "region_id": "person-1", "bbox_norm": [0.2, 0.2, 0.4, 0.8],
                    "semantic_label": "person", "risk": "critical",
                    "confidence": 0.91, "motion_evidence": "none",
                }],
                "uncertainty": 0.15,
            }

    class Policy:
        policy_name, checkpoint_sha256 = "TGRPO+SAC", "c" * 64

        def select(self, state):
            return 1, (0.1, 0.1, 0.0)

        if group_policy:
            def select_group(self, state, *, k, m):
                return [(1, (0.1, 0.1, 0.0), -0.2), (2, (0.1, -0.1, 0.0), -0.2)] * 3

    class Selector:
        selector_name, ensemble_sha256 = "high-level-distilled-ensemble", "e" * 64

        def select_skill_or_fallback(self, state):
            values = {
                "use_learned": True, "skill": 2, "skill_name": "REROUTE_RIGHT",
                "mean_probs": (0.05, 0.15, 0.7, 0.05, 0.05), "entropy": 1.02,
                "unanimous": True, "reason": "confident",
            }
            values.update(decision_kwargs)
            return SelectorDecision(**values)

    class Client:
        def __init__(self):
            self.payloads = []

        def create(self, payload):
            self.payloads.append(payload)
            return {"status": "pending"}

    client = Client()
    RecoveryInferenceWorker(Vlm(), Policy(), client, skill_selector=Selector()).process(
        object(),
        [DetectionEvidence("person", 0.91, (0.2, 0.2, 0.4, 0.8), "track-1")],
        NavigationContext(
            device_id="PK_01", map_name="new_map_2", map_revision="new_map_2-r1",
            robot_pose=(1.0, 2.0, 0.0), goal_pose=(3.0, 4.0),
            navigation_state="stuck", stuck_seconds=4.0,
        ),
    )
    return client.payloads[0]


@pytest.mark.parametrize("decision_kwargs", [
    {},
    {"skill": 0, "skill_name": "BACKUP"},
    {"use_learned": False, "skill": None, "skill_name": None, "entropy": 1.58,
     "unanimous": False, "reason": "uncertain"},
])
def test_every_worker_proposal_satisfies_the_gateway_contract(decision_kwargs) -> None:
    payload = _worker_payload(decision_kwargs)
    payload["perception_evidence"] = [
        {k: v for k, v in item.items() if k != "track_id"}
        for item in payload["perception_evidence"]
    ]

    RecoveryProposalCreate(**payload)


@pytest.mark.parametrize("decision_kwargs", [
    {},
    {"use_learned": False, "skill": None, "skill_name": None, "entropy": 1.58,
     "unanimous": False, "reason": "uncertain"},
])
def test_single_select_policies_also_satisfy_the_gateway_contract(decision_kwargs) -> None:
    payload = _worker_payload(decision_kwargs, group_policy=False)
    payload["perception_evidence"] = [
        {k: v for k, v in item.items() if k != "track_id"}
        for item in payload["perception_evidence"]
    ]

    RecoveryProposalCreate(**payload)
