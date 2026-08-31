from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TrainingConfig:
    model: str
    data: Path
    run_root: Path
    name: str | None = None
    augmentation: bool = True
    augmentation_seed: int = 42
    # Scenarios kept out of training, for leave-one-out experiments.
    augmentation_holdout: tuple[str, ...] = ()
    epochs: int = 200
    imgsz: int = 640
    patience: int = 20
    batch: int = -1
    device: str = "auto"
    workers: int = 8
    seed: int = 42
    deterministic: bool = True
    posture_manifest: Path | None = None
    # Module holding the augmentation recipes. None uses the repo default,
    # vision_ai/utils/augmentation/scenarios.py; a path swaps in another set
    # without editing code.
    augmentation_source: Path | None = None
    allow_posture_gap: bool = False
    preflight_only: bool = False
    min_fallen_per_eval_split: int = 10
    min_mask_recall: float = 0.90
    min_mask_map50: float = 0.80
    test_on_validation_gate_failure: bool = False
    # Mirror metrics to a wandb run. Off by default: a compute node with no
    # network must still train.
    wandb: bool = False
    wandb_project: str = "trihouse-vision"

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", Path(self.data).expanduser().resolve())
        object.__setattr__(self, "run_root", Path(self.run_root).expanduser().resolve())
        if self.posture_manifest is not None:
            object.__setattr__(self, "posture_manifest", Path(self.posture_manifest).expanduser().resolve())
        if self.augmentation_source is not None:
            object.__setattr__(self, "augmentation_source", Path(self.augmentation_source).expanduser().resolve())
        if self.epochs <= 0 or self.imgsz <= 0 or self.patience < 0 or self.workers < 0:
            raise ValueError("epochs/imgsz는 양수이고 patience/workers는 0 이상이어야 합니다")
        for field_name in ("min_mask_recall", "min_mask_map50"):
            value = getattr(self, field_name)
            if value < 0 or value > 1:
                raise ValueError(f"{field_name}는 0..1 범위여야 합니다")

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["augmentation_holdout"] = list(values["augmentation_holdout"])
        for key in ("data", "run_root", "posture_manifest", "augmentation_source"):
            if values[key] is not None:
                values[key] = str(values[key])
        return values

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "TrainingConfig":
        allowed = cls.__dataclass_fields__.keys()
        kept = {key: value for key, value in values.items() if key in allowed}
        if "augmentation_holdout" in kept:
            kept["augmentation_holdout"] = tuple(kept["augmentation_holdout"])
        return cls(**kept)
