import json
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from pipeline.orchestrator import PipelineError, run_pipeline
from pipeline.run_config import TrainingConfig


def make_dataset(root: Path) -> Path:
    for index, split in enumerate(("train", "valid", "test")):
        (root / split / "images").mkdir(parents=True)
        (root / split / "labels").mkdir(parents=True)
        cv2.imwrite(str(root / split / "images" / f"{split}.jpg"), np.full((8, 8, 3), index))
        (root / split / "labels" / f"{split}.txt").write_text(
            "1 0.1 0.1 0.8 0.1 0.8 0.8 0.1 0.8\n", encoding="utf-8"
        )
    data = {"train": "train/images", "val": "valid/images", "test": "test/images", "nc": 2, "names": ["obstacle", "person"]}
    path = root / "data.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


class FakeBackend:
    def __init__(self, *, fail_train: bool = False, recall: float = 0.95, map50: float = 0.85):
        self.calls: list[str] = []
        self.fail_train = fail_train
        self.recall = recall
        self.map50 = map50

    def train(self, config: TrainingConfig, run_dir: Path) -> Path:
        self.calls.append("train")
        if self.fail_train:
            raise RuntimeError("GPU exploded")
        weights = run_dir / "train/weights/best.pt"
        weights.parent.mkdir(parents=True)
        weights.write_bytes(b"weights")
        return weights

    def evaluate(self, weights: Path, split: str, config: TrainingConfig, run_dir: Path) -> dict[str, float]:
        self.calls.append(f"evaluate:{split}")
        return {"mask_recall": self.recall, "mask_map50": self.map50, "mask_map50_95": 0.6, "box_recall": 0.9, "box_map50": 0.8, "box_map50_95": 0.55}


class PersonMetricBackend(FakeBackend):
    def evaluate(self, weights, split, config, run_dir):
        self.calls.append(f"evaluate:{split}")
        return {"mask_recall": .99, "mask_map50": .99, "person_mask_recall": .4, "person_mask_map50": .3, "mask_map50_95": .8}


def config(tmp_path: Path, data: Path, **updates) -> TrainingConfig:
    values = dict(model="26s", data=data, run_root=tmp_path / "runs", name="unit", allow_posture_gap=True)
    values.update(updates)
    return TrainingConfig(**values)


def test_config_serialization_is_deterministic(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")
    first = config(tmp_path, data).to_dict()
    second = config(tmp_path, data).to_dict()
    assert first == second
    assert first["augmentation"] is True
    assert first["model"] == "26s"


def test_pipeline_runs_validation_before_test_and_writes_manifest(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")
    backend = FakeBackend()

    run_dir = run_pipeline(config(tmp_path, data), backend)

    assert backend.calls == ["train", "evaluate:val", "evaluate:test"]
    status = json.loads((run_dir / "status.json").read_text())
    manifest = json.loads((run_dir / "artifact_manifest.json").read_text())
    assert status["state"] == "COMPLETED"
    assert manifest["model"]["class_name"] == "person"
    assert manifest["model"]["class_id"] == 1
    assert manifest["weights"].endswith("best.pt")
    assert manifest["seeds"] == {"training": 42, "augmentation": 42}
    assert (run_dir / "evaluation/validation_metrics.json").is_file()
    assert (run_dir / "evaluation/test_metrics.json").is_file()


def test_pipeline_records_failed_stage(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")

    with pytest.raises(RuntimeError, match="GPU exploded"):
        run_pipeline(config(tmp_path, data), FakeBackend(fail_train=True))

    status = json.loads((tmp_path / "runs/unit/status.json").read_text())
    assert status["state"] == "FAILED"
    assert status["stage"] == "TRAIN"
    assert "GPU exploded" in status["error"]


def test_pipeline_stops_before_test_when_validation_gate_fails(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")
    backend = FakeBackend(recall=0.5)

    with pytest.raises(PipelineError, match="validation gate"):
        run_pipeline(config(tmp_path, data), backend)

    assert backend.calls == ["train", "evaluate:val"]
    status = json.loads((tmp_path / "runs/unit/status.json").read_text())
    assert status["state"] == "FAILED"
    assert status["stage"] == "VALIDATION_GATE"


def test_preflight_only_never_invokes_backend(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")
    backend = FakeBackend()

    run_dir = run_pipeline(config(tmp_path, data, preflight_only=True), backend)

    assert backend.calls == []
    assert json.loads((run_dir / "status.json").read_text())["state"] == "PREFLIGHT_COMPLETED"


def test_validation_gate_prefers_person_metrics_over_macro_average(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")
    with pytest.raises(PipelineError, match="validation gate"):
        run_pipeline(config(tmp_path, data), PersonMetricBackend())
