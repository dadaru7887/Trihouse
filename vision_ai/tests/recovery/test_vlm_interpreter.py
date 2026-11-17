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


def test_versions_share_sections_and_differ_only_where_they_say() -> None:
    from vision_ai.models.recovery.vlm_interpreter import load_prompts, render_prompt

    prompts = load_prompts()
    evidence = [DetectionEvidence("person", 0.91, (0.0, 0.0, 0.2, 0.4), None, "r1")]
    v1 = render_prompt("v1", evidence, "goal", prompts)
    v2 = render_prompt("v2", evidence, "goal", prompts)

    assert v1 == v2 + "\n\n" + prompts["sections"]["field_notes"]
    assert ("- region_id=r1, class=person, yoloe_confidence=0.91, "
            "bbox_norm=[0.000, 0.000, 0.200, 0.400], position=TOP-LEFT, track_id=null") in v1
    assert '"region_id": "{region_id}"' in v1                  # placeholders reach the model
    assert "- person: TOP-LEFT region, confidence 0.91" in render_prompt("current", evidence, "goal", prompts)


def test_every_version_reports_scene_confidence_under_one_name() -> None:
    from vision_ai.models.recovery.vlm_interpreter import load_prompts, parse_response

    prompts = load_prompts()

    assert parse_response('{"observations": [], "uncertainty": 0.7}', "current", prompts) == {
        "observations": [], "scene_confidence": 0.7}
    assert parse_response('{"scene_confidence": 0.4}', "v1", prompts) == {"scene_confidence": 0.4}
    assert parse_response('{"observations": [', "v1", prompts) == {}
