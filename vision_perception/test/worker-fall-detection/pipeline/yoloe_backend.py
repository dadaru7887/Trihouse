import importlib.util
import re
import sys
from pathlib import Path
from typing import Any, Callable

from .run_config import TrainingConfig
from .reproducibility import seed_everything


_MODEL_SHORTHAND = re.compile(r"^(11|26)([nsmlx])$")


def resolve_model(name: str) -> str:
    match = _MODEL_SHORTHAND.fullmatch(name)
    return f"yoloe-{match.group(1)}{match.group(2)}-seg.pt" if match else name


def normalize_metrics(result: Any) -> dict[str, float]:
    if getattr(result, "seg", None) is None:
        raise ValueError("YOLOE evaluation 결과에 segmentation metrics가 없습니다")
    if getattr(result, "box", None) is None:
        raise ValueError("YOLOE evaluation 결과에 box metrics가 없습니다")
    return {
        "box_precision": float(result.box.mp),
        "box_recall": float(result.box.mr),
        "box_map50": float(result.box.map50),
        "box_map50_95": float(result.box.map),
        "mask_precision": float(result.seg.mp),
        "mask_recall": float(result.seg.mr),
        "mask_map50": float(result.seg.map50),
        "mask_map50_95": float(result.seg.map),
    }


def _load_existing_training_module():
    path = Path(__file__).resolve().parents[3] / "segmentation" / "train.py"
    spec = importlib.util.spec_from_file_location("trihouse_segmentation_train", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"기존 train.py를 불러올 수 없습니다: {path}")
    module = importlib.util.module_from_spec(spec)
    # Albumentations callback이 checkpoint 설정에 직렬화될 때 이 module path로
    # 다시 import할 수 있어야 한다.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _default_components() -> tuple[Callable[[str], Any], Any, Callable[[bool, int], list[Any]]]:
    from ultralytics import YOLOE
    from ultralytics.models.yolo.yoloe import YOLOEPESegTrainer

    training = _load_existing_training_module()

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

    def _ensure_components(self) -> None:
        if self.model_factory is not None and self.augmentation_factory is not None:
            return
        default_model, default_trainer, default_augmentations = _default_components()
        self.model_factory = self.model_factory or default_model
        self.trainer_class = self.trainer_class or default_trainer
        self.augmentation_factory = self.augmentation_factory or default_augmentations

    def train(self, config: TrainingConfig, run_dir: Path) -> Path:
        seed_everything(config.seed, config.deterministic)
        self._ensure_components()
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
        self._ensure_components()
        assert self.model_factory is not None
        if split not in {"val", "test"}:
            raise ValueError(f"평가 split은 val 또는 test여야 합니다: {split}")
        if not weights.is_file():
            raise FileNotFoundError(f"평가 weight가 없습니다: {weights}")
        model = self.model_factory(str(weights))
        result = model.val(
            data=str(config.data), split=split, imgsz=config.imgsz, batch=config.batch,
            device=config.device, workers=config.workers,
            project=str(run_dir / "evaluation"), name=split, exist_ok=True,
        )
        return normalize_metrics(result)
