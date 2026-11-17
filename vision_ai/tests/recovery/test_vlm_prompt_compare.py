"""Offline prompt comparison: tracker per recording, review rows per labelled
object, resumable responses. YOLOE and Qwen are replaced by fakes.

    pytest vision_ai/tests/recovery/test_vlm_prompt_compare.py
"""

from __future__ import annotations

import csv
import json

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from vision_ai.models.perception.detector import Detection
from vision_ai.tooling import vlm_prompt_compare as compare


def _dataset(root):
    """Two recordings, frames written out of order; one person per frame."""
    (root / "valid" / "images").mkdir(parents=True)
    (root / "valid" / "labels").mkdir(parents=True)
    (root / "data.yaml").write_text("names: [obstacle, person]\n", encoding="utf-8")
    names = [f"dataset_video_20260822_{rec}_t{t:04d}-00s_jpg.rf.x" for rec, t in
             (("111111", 2), ("111111", 1), ("222222", 1))]
    for name in names:
        cv2.imwrite(str(root / "valid" / "images" / f"{name}.jpg"), np.zeros((40, 40, 3), np.uint8))
        (root / "valid" / "labels" / f"{name}.txt").write_text(
            "1 0.5 0.25 0.75 0.25 0.75 0.75 0.5 0.75\n", encoding="utf-8")
    return root


class FakeDetector:
    """predict sees both objects; the tracker returns only the person, id 5."""

    calls: list[str] = []

    def __init__(self, weights, config):
        self.tracking = config.tracking

    def load(self):
        pass

    def reset_tracking(self):
        FakeDetector.calls.append("reset")

    def detect(self, frame):
        person = Detection(1, 0.8, None, "5" if self.tracking else "", (0.5, 0.25, 0.75, 0.75))
        if self.tracking:
            FakeDetector.calls.append("track")
            return [person]
        return [person, Detection(0, 0.4, None, "", (0.0, 0.0, 0.2, 0.2))]


class FakeVlm:
    received: list = []

    def __init__(self, revision):
        pass

    def interpret(self, frame, detections, goal_text, version=None):
        FakeVlm.received.append(list(detections))
        risk = "critical" if version == "v1" else "low"
        return {"observations": [{"region_id": "r2", "semantic_label": "person",
                                  "bbox_norm": [0.5, 0.25, 0.75, 0.75], "risk": risk,
                                  "confidence": 0.9, "evidence": "in the corridor"}],
                "scene_confidence": 0.8, "raw_response": "{...}", "output_tokens": 50,
                "truncated": False, "seconds": 1.0}


def test_compare_runs_end_to_end_and_resumes(tmp_path, monkeypatch):
    import vision_ai.models.perception.detector as detector
    import vision_ai.models.recovery.vlm_interpreter as interpreter

    monkeypatch.setattr(detector, "Detector", FakeDetector)
    monkeypatch.setattr(interpreter, "QwenVlmInterpreter", FakeVlm)
    dataset, out = _dataset(tmp_path / "data"), tmp_path / "out"

    compare.main(["--dataset", str(dataset), "--weights", "w.pt", "--out", str(out),
                  "--versions", "current", "v1"])

    assert FakeDetector.calls == ["reset", "track", "track", "reset", "track"]
    rows = [json.loads(line) for line in (out / "detections.jsonl").read_text().splitlines()]
    assert [r["t_s"] for r in rows] == [1.0, 2.0, 1.0]                  # time order per recording
    assert rows[0]["gt"][0] | {"iou": 1} == {"class_name": "person", "bbox_xyxy_norm": [0.5, 0.25, 0.75, 0.75],
                                             "gt_object_id": "g1", "region_id": "r2", "iou": 1}

    review = list(csv.DictReader((out / "review.csv").open(encoding="utf-8")))
    labelled = [r for r in review if r["gt_object_id"]]
    assert {(r["v1_risk"], r["current_risk"], r["risk_label"], r["track_id"]) for r in labelled} == {
        ("critical", "low", "critical", "5")}
    assert {(r["gt_class"], r["track_id"]) for r in review if not r["gt_object_id"]} == {
        ("(no label)", "")}                                               # untracked: null
    # The ByteTrack id stored with the YOLOE result is the one the VLM is given.
    from vision_ai.models.recovery.vlm_interpreter import load_prompts, render_prompt
    given = {e.region_id: e.track_id for e in FakeVlm.received[0]}
    assert given == {d["region_id"]: d["track_id"] for d in rows[0]["detections"]} == {"r1": None, "r2": "5"}
    prompt = render_prompt("v1", FakeVlm.received[0], "goal", load_prompts())
    assert "region_id=r2, class=person" in prompt and "track_id=5" in prompt
    assert "region_id=r1, class=obstacle" in prompt and "track_id=null" in prompt

    summary = json.loads((out / "summary.json").read_text())
    assert summary["v1"]["region_missing_rate"] == 0.5                 # r1 never answered
    assert any((out / "overlays").iterdir())

    before = (out / "responses.jsonl").read_text()
    compare.main(["--dataset", str(dataset), "--out", str(out), "--versions", "current", "v1"])
    assert (out / "responses.jsonl").read_text() == before            # nothing asked twice
