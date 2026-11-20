from vision_ai.models.recovery.vlm_interpreter import build_detections_text, parse_json_response
from vision_ai.robot.recovery.worker import DetectionEvidence


def test_vlm_json_parser_accepts_a_fenced_object_but_rejects_non_json() -> None:
    assert parse_json_response('```json\n{"observations": [], "uncertainty": 0.5}\n```') == {
        "observations": [], "uncertainty": 0.5
    }
    assert parse_json_response("drive left") is None


def test_detection_prompt_text_keeps_class_position_and_confidence() -> None:
    text = build_detections_text([
        DetectionEvidence("person", 0.91, (0.0, 0.0, 0.2, 0.4), "p1")
    ])

    assert text == "- person: TOP-LEFT region, confidence 0.91"


def test_versions_render_the_fixed_goal_and_their_own_detection_list() -> None:
    from vision_ai.models.recovery.vlm_interpreter import load_prompts, render_prompt

    prompts = load_prompts()
    evidence = [DetectionEvidence("person", 0.91, (0.0, 0.0, 0.2, 0.4), None, "r1")]
    v1, current = (render_prompt(v, evidence, prompts) for v in ("v1", "current"))

    assert sorted(prompts["versions"]) == ["current", "v1"]
    assert ("- region_id=r1, class=person, yoloe_confidence=0.91, "
            "bbox_norm=[0.000, 0.000, 0.200, 0.400], position=TOP-LEFT, track_id=null") in v1
    assert '"region_id": "{region_id}"' in v1                  # placeholders reach the model
    assert "- scene_confidence: Report confidence" in v1        # field notes are part of the format
    assert "- person: TOP-LEFT region, confidence 0.91" in current
    for text in (v1, current):
        assert "toward the next waypoint" in text and "{goal}" not in text
        assert '"scene_confidence"' in text and "uncertainty" not in text
