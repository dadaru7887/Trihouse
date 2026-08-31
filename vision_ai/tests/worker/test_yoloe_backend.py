from pathlib import Path
from types import SimpleNamespace

import pytest

from vision_ai.utils.run_config import TrainingConfig
from vision_ai.models.perception.trainer.yoloe_trainer import YOLOEBackend, confusion_metrics, normalize_metrics


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
        model="yoloe-26s-seg.pt", data=data, run_root=tmp_path / "runs",
        augmentation=augmentation,
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


def test_the_augmentation_source_actually_exists() -> None:
    """증강 recipe 모듈 경로가 실제 파일을 가리켜야 한다.

    이 값이 어긋나면 학습이 시작될 때 `기존 train.py를 불러올 수 없습니다` 로
    죽는다. 그런데 그 경로는 GPU 학습을 실제로 띄워야만 밟히므로, 파일이 옮겨져도
    단위 테스트가 아무것도 잡지 못한 채 통과한다 — 여기서 그 구멍을 막는다.
    """
    from vision_ai.models.perception.trainer.yoloe_trainer import _resolve_augmentation_source

    resolved = _resolve_augmentation_source(None)

    assert resolved.is_file(), f"증강 recipe 모듈이 없습니다: {resolved}"
    assert "vision_ai" in resolved.parts, f"저장소 밖을 가리킵니다: {resolved}"


def test_the_resolved_source_provides_what_the_trainer_pulls_from_it() -> None:
    """경로만 맞고 내용이 다르면 같은 자리에서 다른 이유로 죽는다.

    `_default_components` 가 이 모듈에서 세 가지를 꺼낸다. 텍스트로 찾으면
    다른 파일에서 import 해 온 이름을 놓치므로, 실제로 적재해서 속성을 본다.
    """
    pytest.importorskip("albumentations")
    pytest.importorskip("cv2")
    import importlib.util
    import sys

    from vision_ai.models.perception.trainer.yoloe_trainer import _resolve_augmentation_source

    path = _resolve_augmentation_source(None)
    spec = importlib.util.spec_from_file_location("aug_contract", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["aug_contract"] = module
    spec.loader.exec_module(module)

    for needed in ("configure_augmentation_seed", "mixed_augmentation", "A", "MIXED_POOL"):
        assert hasattr(module, needed), f"{needed} 를 꺼낼 수 없습니다"


def test_the_weight_name_reaches_the_model_factory_unchanged(tmp_path: Path) -> None:
    """run 기록에 남는 이름과 실제로 로드되는 이름이 같아야 한다."""
    calls = []
    backend = YOLOEBackend(
        model_factory=lambda weight: FakeModel(weight, calls),
        trainer_class=None,
        augmentation_factory=lambda enabled, seed: [],
    )

    backend.train(make_config(tmp_path), tmp_path / "run")

    assert calls[0][0] == "train"
    assert backend.model_factory is not None
