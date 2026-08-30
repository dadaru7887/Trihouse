import json

import pytest

from vision_ai.robot.recovery.collection.collector import DriveDatasetCollector


def completion(*, executed: bool = True) -> dict:
    return {"transition": {
        "state": [0.0] * 9, "skill": 3, "coord": [0.0, 0.0, 0.0],
        "reward": 0.1, "next_state": [0.0] * 9, "done": True,
        "meta": {"is_execution": executed, "proposal_id": "p1"},
    }}


def test_continuous_navigation_and_trainable_recovery_are_separate(tmp_path):
    collector = DriveDatasetCollector(tmp_path)
    collector.record_navigation_event({
        "source": "nav2", "event_type": "state", "device_id": "PK-01",
        "navigation_state": "navigating", "frame_ref": "rtsp://recording/42",
    })
    collector.record_navigation_event({
        "source": "rule", "event_type": "intervention", "device_id": "PK-01",
        "rule_id": "battery_critical", "action": "return_to_charge",
    })
    collector.record_recovery_completion(completion())

    navigation = [json.loads(line) for line in collector.navigation_path.read_text().splitlines()]
    recovery = [json.loads(line) for line in collector.recovery_path.read_text().splitlines()]
    assert [item["source"] for item in navigation] == ["nav2", "rule"]
    assert len(recovery) == 1
    assert recovery[0]["meta"]["dataset_schema_id"] == "trihouse.recovery-transition.v1"


def test_observation_only_recovery_cannot_enter_training_dataset(tmp_path):
    collector = DriveDatasetCollector(tmp_path)
    with pytest.raises(ValueError, match="actually executed"):
        collector.record_recovery_completion(completion(executed=False))
    assert not collector.recovery_path.exists()
