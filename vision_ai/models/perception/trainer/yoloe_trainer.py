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
    """Return the weight name unchanged; refuse a shorthand rather than expand it.

    A run's record must name the weights that were actually loaded, so `26s`
    is an error rather than a silent rewrite to `yoloe-26s-seg.pt`.
    """
    if _MODEL_SHORTHAND.fullmatch(name):
        raise ValueError(
            f"write the full weight name instead of a shorthand: {name!r} "
            f"-> 'yoloe-{name}-seg.pt'"
        )
    return name


def normalize_metrics(result: Any) -> dict[str, float]:
    if getattr(result, "seg", None) is None:
        raise ValueError("the YOLOE evaluation result has no segmentation metrics")
    if getattr(result, "box", None) is None:
        raise ValueError("the YOLOE evaluation result has no box metrics")
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


def _load_augmentation_module(source: Path | None = None):
    """Load the recipe registry, or a drop-in replacement from `source`.

    `source` lets a run swap in a different recipe set without editing code;
    it must expose the same names as scenarios.py.
    """
    if source is None:
        from vision_ai.utils.augmentation import scenarios

        return scenarios
    path = Path(source).expanduser().resolve()
    spec = importlib.util.spec_from_file_location("trihouse_augmentation_scenarios", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the augmentation recipe module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _default_components(
    augmentation_source: Path | None = None,
) -> tuple[Callable[[str], Any], Any, Callable[[bool, int], list[Any]]]:
    from ultralytics import YOLOE
    from ultralytics.models.yolo.yoloe import YOLOEPESegTrainer

    training = _load_augmentation_module(augmentation_source)

    def augmentations(enabled: bool, augmentation_seed: int,
                      holdout: tuple[str, ...] = ()) -> list[Any]:
        training.configure_augmentation_seed(augmentation_seed)
        training.configure_pool(exclude=set(holdout))
        if not enabled:
            return []
        return [training.A.Lambda(image=training.mixed_augmentation, p=1.0,
                                  name="mixed_train_recipes")]

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
        if config.wandb:
            # The orchestrator already called wandb.init, and ultralytics'
            # callback reuses an open run rather than starting a second one,
            # so our config and its per-epoch metrics land together.
            from ultralytics.utils import SETTINGS

            SETTINGS["wandb"] = True
        self._ensure_components(config.augmentation_source)
        assert self.model_factory is not None and self.augmentation_factory is not None
        model = self.model_factory(resolve_model(config.model))
        transforms = self.augmentation_factory(
            config.augmentation, config.augmentation_seed, config.augmentation_holdout)

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
            raise RuntimeError(f"YOLOE training produced no best.pt: {best}")
        return best

    def evaluate(
        self, weights: Path, split: str, config: TrainingConfig, run_dir: Path
    ) -> dict[str, float]:
        self._ensure_components(config.augmentation_source)
        assert self.model_factory is not None
        if split not in {"val", "test"}:
            raise ValueError(f"the evaluation split must be val or test: {split}")
        if not weights.is_file():
            raise FileNotFoundError(f"evaluation weights not found: {weights}")
        model = self.model_factory(str(weights))
        result = model.val(
            data=str(config.data), split=split, imgsz=config.imgsz, batch=config.batch,
            device=config.device, workers=config.workers,
            project=str(run_dir / "evaluation"), name=split, exist_ok=True, plots=True,
        )
        return normalize_metrics(result)
