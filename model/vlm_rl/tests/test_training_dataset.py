import json
from pathlib import Path

import pytest

from model.vlm_rl.training.dataset import load_training_jsonl


def record() -> dict:
    return {
        "state": [0.0] * 9,
        "skill": 4,
        "coord": [0.1, 0.0, 0.0],
        "reward": 0.2,
        "next_state": [0.1] + [0.0] * 8,
        "done": True,
        "meta": {"is_execution": True, "episode_uuid": "episode-1", "step_no": 1},
    }


def test_jsonl_round_trips_to_the_frozen_training_tuple(tmp_path: Path) -> None:
    path = tmp_path / "recovery.jsonl"
    path.write_text(json.dumps(record()) + "\n", encoding="utf-8")
    transition = load_training_jsonl(path)[0]
    assert transition.skill == 4
    assert transition.coord == (0.1, 0.0, 0.0)
    assert len(transition.state) == len(transition.next_state) == 9


def test_loader_reports_line_and_never_fills_missing_state(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    bad = record()
    bad["state"] = [0.0] * 8
    path.write_text("\n" + json.dumps(bad) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        load_training_jsonl(path)
