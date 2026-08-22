from model.vlm_rl.inference.vlm_interpreter import build_detections_text, parse_json_response
from model.vlm_rl.inference.worker import DetectionEvidence


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
