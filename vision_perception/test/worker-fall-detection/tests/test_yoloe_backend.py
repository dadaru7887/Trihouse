from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.run_config import TrainingConfig
from trainer.yoloe_trainer import YOLOEBackend, confusion_metrics, normalize_metrics


class FakeModel:
    def __init__(self, weight: str, calls: list):
        self.weight = weight
        self.calls = calls
        self.callbacks = []

    def add_callback(self, name, callback):
        self.callbacks.append((name, callback))

    def train(self, **kwargs):
        self.calls.append(("train", kwargs))
        save_dir = Path(kwargs["project"]) / kwargs["name"]
        (save_dir / "weights").mkdir(parents=True)
        (save_dir / "weights/best.pt").write_bytes(b"best")
        return SimpleNamespace(save_dir=save_dir)

    def val(self, **kwargs):
        self.calls.append(("val", kwargs))
        return SimpleNamespace(
            box=SimpleNamespace(mp=0.91, mr=0.92, map50=0.93, map=0.71),
            seg=SimpleNamespace(mp=0.94, mr=0.95, map50=0.96, map=0.73),
        )


def make_config(tmp_path: Path, augmentation: bool = False) -> TrainingConfig:
    data = tmp_path / "data.yaml"
    data.write_text("names: [obstacle, person]\n", encoding="utf-8")
    return TrainingConfig(
        model="26s", data=data, run_root=tmp_path / "runs", augmentation=augmentation,
        epochs=3, imgsz=320, patience=2, batch=4, device="0", workers=1, seed=7,
        allow_posture_gap=True,
    )


def test_backend_passes_resolved_training_arguments_and_returns_best(tmp_path: Path) -> None:
    calls = []
    backend = YOLOEBackend(
        model_factory=lambda weight: FakeModel(weight, calls),
        trainer_class="trainer-sentinel",
        augmentation_factory=lambda enabled, seed: [("augmentation", seed)] if enabled else [],
    )
    run_dir = tmp_path / "run"

    best = backend.train(make_config(tmp_path), run_dir)

    kind, args = calls[0]
    assert kind == "train"
    assert args == {
        "data": str((tmp_path / "data.yaml").resolve()),
        "epochs": 3, "imgsz": 320, "patience": 2, "batch": 4,
        "device": "0", "workers": 1, "seed": 7, "deterministic": True,
        "project": str(run_dir), "name": "train", "exist_ok": True,
        "trainer": "trainer-sentinel",
    }
    assert best == run_dir / "train/weights/best.pt"


def test_backend_evaluates_explicit_split_and_normalizes_metrics(tmp_path: Path) -> None:
    calls = []
    backend = YOLOEBackend(
        model_factory=lambda weight: FakeModel(weight, calls),
        trainer_class=None,
        augmentation_factory=lambda enabled, seed: [],
    )
    weights = tmp_path / "best.pt"
    weights.write_bytes(b"best")

    metrics = backend.evaluate(weights, "test", make_config(tmp_path), tmp_path / "run")

    assert calls == [("val", {
        "data": str((tmp_path / "data.yaml").resolve()), "split": "test",
        "imgsz": 320, "batch": 4, "device": "0", "workers": 1,
        "project": str(tmp_path / "run/evaluation"), "name": "test", "exist_ok": True, "plots": True,
    })]
    assert metrics == {
        "box_precision": 0.91, "box_recall": 0.92, "box_map50": 0.93, "box_map50_95": 0.71,
        "mask_precision": 0.94, "mask_recall": 0.95, "mask_map50": 0.96, "mask_map50_95": 0.73,
    }


def test_normalize_metrics_rejects_detection_only_results() -> None:
    result = SimpleNamespace(box=SimpleNamespace(mp=1, mr=1, map50=1, map=1), seg=None)
    try:
        normalize_metrics(result)
    except ValueError as error:
        assert "segmentation" in str(error)
    else:
        raise AssertionError("segmentation metrics 없이 성공하면 안 됩니다")


def test_normalize_metrics_includes_person_class_metrics() -> None:
    metric = SimpleNamespace(mp=.5, mr=.6, map50=.7, map=.4, class_result=lambda index: (.8, .9, .85, .65))
    result = SimpleNamespace(box=metric, seg=metric, names={0: "obstacle", 1: "person"})
    metrics = normalize_metrics(result)
    assert metrics["person_mask_precision"] == .8
    assert metrics["person_mask_recall"] == .9
    assert metrics["person_mask_map50"] == .85
    assert metrics["person_mask_map50_95"] == .65


def test_confusion_metrics_compute_person_instance_f1() -> None:
    # Rows are predicted classes, columns are true classes; final index is background.
    matrix = [[7, 1, 2], [0, 8, 1], [3, 2, 0]]
    metrics = confusion_metrics(matrix, person_id=1)
    assert metrics["person_box_tp"] == 8
    assert metrics["person_box_fp"] == 1
    assert metrics["person_box_fn"] == 3
    assert metrics["person_box_f1"] == pytest.approx(16 / 20)
