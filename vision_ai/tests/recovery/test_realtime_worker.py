import pytest
from vision_ai.robot.recovery.navigation_context import GatewayNavigationContextSource, NavigationContext
from vision_ai.robot.recovery.worker import DetectionEvidence, RecoveryInferenceWorker


class FakeVlm:
    model_name = "Qwen/Qwen2.5-VL-7B-Instruct"
    model_revision = "approved"

    def interpret(self, frame, detections):
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
            "scene_confidence": 0.15,
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
    assert proposal["state"]["scene_confidence"] == 0.15
    assert proposal["selected_skill_id"] == 1
    assert proposal["selected_skill_name"] == "REROUTE_LEFT"


def test_worker_rejects_invalid_vlm_contract_without_sending_a_proposal() -> None:
    class InvalidVlm(FakeVlm):
        def interpret(self, frame, detections):
            return {"observations": "not-a-list", "scene_confidence": 0.1}

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


class GroupPolicy(FakePolicy):
    """Two boundary-safe candidates: REROUTE_LEFT is the goal-distance winner."""

    def select_group(self, state, *, k, m):
        return [(1, (0.1, 0.1, 0.0), -0.2), (2, (0.1, -0.1, 0.0), -0.2)] * 3


class FakeSelector:
    selector_name = "high-level-distilled-ensemble"
    ensemble_sha256 = "e" * 64

    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    def select_skill_or_fallback(self, state):
        self.calls.append(state)
        return self.decision


def decision(**overrides):
    from vision_ai.models.recovery.distilled_selector import SelectorDecision

    values = {
        "use_learned": True, "skill": 2, "skill_name": "REROUTE_RIGHT",
        "mean_probs": (0.05, 0.15, 0.7, 0.05, 0.05), "entropy": 1.02,
        "unanimous": True, "reason": "entropy=1.02<=1.5, unanimous=True",
    }
    values.update(overrides)
    return SelectorDecision(**values)


def test_trusted_selector_overrides_the_goal_distance_winner() -> None:
    client = RecordingProposalClient()
    selector = FakeSelector(decision())
    worker = RecoveryInferenceWorker(FakeVlm(), GroupPolicy(), client, skill_selector=selector)

    worker.process(object(), detections(), context())

    proposal = client.payloads[0]
    assert proposal["selected_skill_id"] == 2
    assert proposal["selected_skill_name"] == "REROUTE_RIGHT"
    assert proposal["skill_selection"]["source"] == "distilled_ensemble"
    assert proposal["skill_selection"]["entropy"] == 1.02
    assert proposal["skill_selection"]["unanimous"] is True
    assert proposal["skill_selection"]["selector_lineage"]["ensemble_sha256"] == "e" * 64
    assert selector.calls == [tuple(proposal["state"].values())]


def test_uncertain_selector_keeps_the_existing_goal_distance_winner() -> None:
    client = RecordingProposalClient()
    selector = FakeSelector(decision(use_learned=False, skill=None, skill_name=None,
                                     entropy=1.58, unanimous=False, reason="uncertain"))
    worker = RecoveryInferenceWorker(FakeVlm(), GroupPolicy(), client, skill_selector=selector)

    worker.process(object(), detections(), context())

    proposal = client.payloads[0]
    assert proposal["selected_skill_id"] == 1
    assert proposal["skill_selection"]["source"] == "goal_distance_fallback"
    assert proposal["skill_selection"]["entropy"] == 1.58


def test_selector_never_revives_a_skill_that_failed_the_motion_boundary() -> None:
    client = RecordingProposalClient()
    # BACKUP is confidently selected but was never sampled, so no bounded candidate exists.
    selector = FakeSelector(decision(skill=0, skill_name="BACKUP"))
    worker = RecoveryInferenceWorker(FakeVlm(), GroupPolicy(), client, skill_selector=selector)

    worker.process(object(), detections(), context())

    proposal = client.payloads[0]
    assert proposal["selected_skill_id"] == 1
    assert proposal["skill_selection"]["source"] == "goal_distance_fallback"
    assert "no bounded candidate" in proposal["skill_selection"]["reason"]


def test_worker_without_a_selector_reports_the_unchanged_goal_distance_source() -> None:
    client = RecordingProposalClient()
    worker = RecoveryInferenceWorker(FakeVlm(), GroupPolicy(), client)

    worker.process(object(), detections(), context())

    proposal = client.payloads[0]
    assert proposal["selected_skill_id"] == 1
    assert proposal["skill_selection"] == {
        "source": "goal_distance", "use_learned": False,
        "reason": "distilled selector is not configured",
    }


def test_unapplied_learned_skill_is_recorded_but_not_marked_as_used() -> None:
    client = RecordingProposalClient()
    selector = FakeSelector(decision(skill=0, skill_name="BACKUP"))
    worker = RecoveryInferenceWorker(FakeVlm(), GroupPolicy(), client, skill_selector=selector)

    worker.process(object(), detections(), context())

    selection = client.payloads[0]["skill_selection"]
    assert selection["use_learned"] is False
    assert selection["learned_skill_name"] == "BACKUP"


@pytest.mark.parametrize("selector_decision", [
    decision(),
    decision(skill=0, skill_name="BACKUP"),
    decision(use_learned=False, skill=None, skill_name=None, entropy=1.58,
             unanimous=False, reason="uncertain"),
])
def test_a_selection_marked_used_always_matches_the_skill_that_was_proposed(selector_decision) -> None:
    client = RecordingProposalClient()
    worker = RecoveryInferenceWorker(
        FakeVlm(), GroupPolicy(), client, skill_selector=FakeSelector(selector_decision)
    )

    worker.process(object(), detections(), context())

    proposal = client.payloads[0]
    selection = proposal["skill_selection"]
    if selection["use_learned"]:
        assert selection["source"] == "distilled_ensemble"
        assert selection["learned_skill_id"] == proposal["selected_skill_id"]
    else:
        assert selection["source"] != "distilled_ensemble"


def test_the_state_box_is_the_yoloe_box_not_the_one_the_vlm_wrote() -> None:
    class DriftingVlm(FakeVlm):
        def interpret(self, frame, detections):
            answer = super().interpret(frame, detections)
            answer["observations"][0].update(region_id="r2", bbox_norm=[0.0, 0.0, 0.1, 0.1])
            return answer

    evidence = [
        DetectionEvidence("person", 0.91, (0.2, 0.2, 0.4, 0.8), "7", "r1"),
        DetectionEvidence("obstacle", 0.70, (0.6, 0.3, 0.9, 0.9), None, "r2"),
    ]
    client = RecordingProposalClient()
    RecoveryInferenceWorker(DriftingVlm(), FakePolicy(), client).process(object(), evidence, context())

    state = client.payloads[0]["state"]
    assert state["risk_bbox_center_x_norm"] == pytest.approx(0.75)   # r2's YOLOE box
    assert state["risk_bbox_center_y_norm"] == pytest.approx(0.6)


def test_detection_evidence_numbers_left_to_right_and_keeps_the_bytetrack_id() -> None:
    from vision_ai.models.perception.detector import Detection
    from vision_ai.robot.recovery.worker import detection_evidence

    raw = [
        Detection(1, 0.9, None, "12", (0.6, 0.1, 0.8, 0.9)),
        Detection(0, 0.5, None, "", (0.1, 0.2, 0.3, 0.5)),
        Detection(1, 0.4, None, "3", None),                   # no box: dropped
    ]

    evidence = detection_evidence(raw, person_class_id=1)

    assert [(e.region_id, e.class_name, e.track_id) for e in evidence] == [
        ("r1", "obstacle", None), ("r2", "person", "12")]


def test_answers_without_region_ids_are_linked_by_box_overlap() -> None:
    from vision_ai.robot.recovery.worker import link_observations

    evidence = detections()
    answers = [{"bbox_norm": [0.62, 0.3, 0.9, 0.88]}, {"bbox_norm": [0.0, 0.9, 0.05, 1.0]}]

    assert link_observations(answers, evidence) == {1: answers[0]}


def test_the_proposal_says_which_execution_mode_made_it() -> None:
    client = RecordingProposalClient()
    RecoveryInferenceWorker(FakeVlm(), FakePolicy(), client).process(object(), detections(), context())
    RecoveryInferenceWorker(FakeVlm(), FakePolicy(), client,
                            execution_mode="auto_bounded").process(object(), detections(), context())

    assert [p["policy_lineage"]["execution_mode"] for p in client.payloads] == [
        "operator_approved", "auto_bounded"]


def test_track_motion_reads_crossing_and_approaching_from_the_last_second() -> None:
    from vision_ai.robot.recovery.worker import TrackHistory, track_motion

    crossing = [(0.0, (0.20, 0.3, 0.30, 0.8)), (1.0, (0.35, 0.3, 0.45, 0.8))]
    coming = [(0.0, (0.40, 0.4, 0.50, 0.7)), (1.0, (0.39, 0.4, 0.51, 0.8))]

    assert track_motion(crossing) == ("right", False)
    assert track_motion(coming) == ("none", True)
    assert track_motion(crossing[:1]) == ("unknown", None)          # one sample: no motion yet

    history = TrackHistory()
    for now, box in crossing:
        stamped = history.observe([DetectionEvidence("person", 0.9, box, "7", "r1")], now)
    assert (stamped[0].lateral, stamped[0].approaching) == ("right", False)


def test_a_moving_person_leaves_only_the_side_away_from_it() -> None:
    walking_left = [DetectionEvidence("person", 0.91, (0.2, 0.2, 0.4, 0.8), "7", "person-1", "left", False)]
    client = RecordingProposalClient()

    RecoveryInferenceWorker(FakeVlm(), GroupPolicy(), client).process(object(), walking_left, context())

    proposal = client.payloads[0]
    assert proposal["selected_skill_name"] == "REROUTE_RIGHT"           # left would be nearer the goal
    assert {c["rejected_by"] for c in proposal["candidate_evidence"] if c["skill_name"] == "REROUTE_LEFT"} == {
        "person person-1 moving left"}


def test_a_failed_skill_is_not_offered_again_during_the_same_stop() -> None:
    client = RecordingProposalClient()
    worker = RecoveryInferenceWorker(FakeVlm(), GroupPolicy(), client)

    worker.process(object(), detections(), context())
    worker.record_outcome(client.payloads[-1], succeeded=False)         # REROUTE_LEFT failed
    worker.process(object(), detections(), context(robot_pose=(1.05, 2.0, 0.0)))
    worker.process(object(), detections(), context(robot_pose=(2.0, 2.0, 0.0)))   # moved on: new stop

    assert [(p["selected_skill_name"], p["policy_lineage"]["attempt_no"]) for p in client.payloads] == [
        ("REROUTE_LEFT", "1"), ("REROUTE_RIGHT", "2"), ("REROUTE_LEFT", "1")]


def test_a_candidate_heading_into_a_wall_of_the_static_map_is_dropped(tmp_path) -> None:
    np = pytest.importorskip("numpy")
    image_module = pytest.importorskip("PIL.Image")
    from trihouse_pinky_fleet.costmap_view import CostmapSnapshot, CostmapView

    pixels = np.full((100, 100), 254, np.uint8)                      # 3 m x 3 m, 0.03 m cells
    pixels[100 - 74:100 - 69, 30:45] = 0                             # wall at y 2.07-2.2 m, x 0.9-1.35 m
    image_module.fromarray(pixels).save(tmp_path / "map.pgm")
    (tmp_path / "map.yaml").write_text(
        "image: map.pgm\nresolution: 0.03\norigin: [0.0, 0.0, 0.0]\nnegate: 0\n"
        "occupied_thresh: 0.65\nfree_thresh: 0.196\n", encoding="utf-8")
    static_map = CostmapView(global_=CostmapSnapshot.from_map_yaml(tmp_path / "map.yaml"))
    client = RecordingProposalClient()

    RecoveryInferenceWorker(FakeVlm(), GroupPolicy(), client, static_map=static_map).process(
        object(), detections(), context())                           # robot at (1.0, 2.0) facing +x

    proposal = client.payloads[0]
    assert proposal["selected_skill_name"] == "REROUTE_RIGHT"
    assert all(c["rejected_by"].startswith("static map: FOOTPRINT_BLOCKED")
               for c in proposal["candidate_evidence"] if c["skill_name"] == "REROUTE_LEFT")
