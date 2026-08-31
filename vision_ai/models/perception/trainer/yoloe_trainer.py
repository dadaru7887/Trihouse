import importlib.util
import re
import sys
from pathlib import Path
from typing import Any, Callable

from vision_ai.utils.reproducibility import seed_everything
from vision_ai.utils.run_config import TrainingConfig


_MODEL_SHORTHAND = re.compile(r"^(11|26)([nsmlx])$")


def confusion_metrics(matrix: Any, person_id: int) -> dict[str, float | int]:
    import numpy as np
    values = np.asarray(matrix)
    tp = int(values[person_id, person_id])
    fp = int(values[person_id, :].sum() - tp)
    fn = int(values[:, person_id].sum() - tp)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    total = float(values.sum())
    return {
        "person_box_tp": tp, "person_box_fp": fp, "person_box_fn": fn,
        "person_box_precision_cm": precision, "person_box_recall_cm": recall,
        "person_box_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "box_confusion_accuracy": float(np.trace(values) / total) if total else 0.0,
    }


def resolve_model(name: str) -> str:
    """가중치 이름을 그대로 돌려준다. 축약어는 확장하지 않고 거절한다.

    전에는 `26s` 를 `yoloe-26s-seg.pt` 로 조용히 바꿔 줬다. 편하지만 run 기록에
    남은 이름과 실제로 적은 이름이 달라져서, 나중에 "무슨 모델로 학습했나" 를
    되짚을 때 코드를 열어 봐야만 알 수 있었다. 이름은 적은 그대로 쓴다.
    """
    if _MODEL_SHORTHAND.fullmatch(name):
        raise ValueError(
            f"축약어 대신 전체 가중치 이름을 적으십시오: {name!r} "
            f"-> 'yoloe-{name}-seg.pt'"
        )
    return name


def normalize_metrics(result: Any) -> dict[str, float]:
    if getattr(result, "seg", None) is None:
        raise ValueError("YOLOE evaluation 결과에 segmentation metrics가 없습니다")
    if getattr(result, "box", None) is None:
        raise ValueError("YOLOE evaluation 결과에 box metrics가 없습니다")
    metrics = {
        "box_precision": float(result.box.mp),
        "box_recall": float(result.box.mr),
        "box_map50": float(result.box.map50),
        "box_map50_95": float(result.box.map),
        "mask_precision": float(result.seg.mp),
        "mask_recall": float(result.seg.mr),
        "mask_map50": float(result.seg.map50),
        "mask_map50_95": float(result.seg.map),
    }
    names = getattr(result, "names", {})
    person_id = next((int(class_id) for class_id, name in names.items() if name == "person"), None)
    if person_id is not None:
        for prefix, source in (("box", result.box), ("mask", result.seg)):
            precision, recall, map50, map50_95 = source.class_result(person_id)
            metrics.update({
                f"person_{prefix}_precision": float(precision),
                f"person_{prefix}_recall": float(recall),
                f"person_{prefix}_map50": float(map50),
                f"person_{prefix}_map50_95": float(map50_95),
            })
        confusion = getattr(getattr(result, "confusion_matrix", None), "matrix", None)
        if confusion is not None:
            metrics.update(confusion_metrics(confusion, person_id))
    return metrics


# `augmentation_source` 를 주지 않았을 때 찾아갈 자리. 저장소 안의 상대 위치로만
# 두고 절대 경로는 코드에 넣지 않는다 — 다른 체크아웃이나 다른 recipe 로 옮겨도
# `--augmentation-source` 하나로 갈아 끼울 수 있어야 한다.
DEFAULT_AUGMENTATION_SOURCE = Path("vision_ai/models/perception/trainer/augmentation_recipes.py")


def _resolve_augmentation_source(source: Path | None) -> Path:
    if source is not None:
        return Path(source).expanduser().resolve()
    # vision_ai/models/perception/trainer/yoloe_trainer.py -> 저장소 루트는 네 단계 위다.
    # trainer(0) / perception(1) / models(2) / vision_ai(3) / <저장소 루트>(4)
    return (Path(__file__).resolve().parents[4] / DEFAULT_AUGMENTATION_SOURCE).resolve()


def _load_existing_training_module(source: Path | None = None):
    path = _resolve_augmentation_source(source)
    spec = importlib.util.spec_from_file_location("trihouse_segmentation_train", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"증강 recipe 모듈을 불러올 수 없습니다: {path}")
    module = importlib.util.module_from_spec(spec)
    # Albumentations callback이 checkpoint 설정에 직렬화될 때 이 module path로
    # 다시 import할 수 있어야 한다.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _default_components(
    augmentation_source: Path | None = None,
) -> tuple[Callable[[str], Any], Any, Callable[[bool, int], list[Any]]]:
    from ultralytics import YOLOE
    from ultralytics.models.yolo.yoloe import YOLOEPESegTrainer

    training = _load_existing_training_module(augmentation_source)

    def augmentations(enabled: bool, augmentation_seed: int) -> list[Any]:
        training.configure_augmentation_seed(augmentation_seed)
        if not enabled:
            return []
        return [training.A.Lambda(image=training.mixed_augmentation, p=1.0, name="mixed_s1_s5")]

    return YOLOE, YOLOEPESegTrainer, augmentations


class YOLOEBackend:
    requires_cuda = True
    def __init__(
        self,
        model_factory: Callable[[str], Any] | None = None,
        trainer_class: Any = None,
        augmentation_factory: Callable[[bool, int], list[Any]] | None = None,
    ) -> None:
        self.model_factory = model_factory
        self.trainer_class = trainer_class
        self.augmentation_factory = augmentation_factory

    def _ensure_components(self, augmentation_source: Path | None = None) -> None:
        if self.model_factory is not None and self.augmentation_factory is not None:
            return
        default_model, default_trainer, default_augmentations = _default_components(augmentation_source)
        self.model_factory = self.model_factory or default_model
        self.trainer_class = self.trainer_class or default_trainer
        self.augmentation_factory = self.augmentation_factory or default_augmentations

    def train(self, config: TrainingConfig, run_dir: Path) -> Path:
        seed_everything(config.seed, config.deterministic)
        self._ensure_components(config.augmentation_source)
        assert self.model_factory is not None and self.augmentation_factory is not None
        model = self.model_factory(resolve_model(config.model))
        transforms = self.augmentation_factory(config.augmentation, config.augmentation_seed)

        def set_augmentations(trainer: Any) -> None:
            trainer.args.augmentations = transforms

        model.add_callback("on_pretrain_routine_start", set_augmentations)
        kwargs = {
            "data": str(config.data), "epochs": config.epochs, "imgsz": config.imgsz,
            "patience": config.patience, "batch": config.batch, "device": config.device,
            "workers": config.workers, "seed": config.seed, "deterministic": config.deterministic,
            "project": str(run_dir),
            "name": "train", "exist_ok": True, "trainer": self.trainer_class,
        }
        result = model.train(**kwargs)
        save_dir = Path(result.save_dir)
        best = save_dir / "weights/best.pt"
        if not best.is_file():
            raise RuntimeError(f"YOLOE 학습 결과 best.pt가 없습니다: {best}")
        return best

    def evaluate(
        self, weights: Path, split: str, config: TrainingConfig, run_dir: Path
    ) -> dict[str, float]:
        self._ensure_components(config.augmentation_source)
        assert self.model_factory is not None
        if split not in {"val", "test"}:
            raise ValueError(f"평가 split은 val 또는 test여야 합니다: {split}")
        if not weights.is_file():
            raise FileNotFoundError(f"평가 weight가 없습니다: {weights}")
        model = self.model_factory(str(weights))
        result = model.val(
            data=str(config.data), split=split, imgsz=config.imgsz, batch=config.batch,
            device=config.device, workers=config.workers,
            project=str(run_dir / "evaluation"), name=split, exist_ok=True, plots=True,
        )
        return normalize_metrics(result)
