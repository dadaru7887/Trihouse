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
    epochs: int = 200
    imgsz: int = 640
    patience: int = 20
    batch: int = -1
    device: str = "0"
    workers: int = 8
    seed: int = 42
    posture_manifest: Path | None = None
    allow_posture_gap: bool = False
    preflight_only: bool = False
    min_fallen_per_eval_split: int = 10
    min_mask_recall: float = 0.90
    min_mask_map50: float = 0.80

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", Path(self.data).expanduser().resolve())
        object.__setattr__(self, "run_root", Path(self.run_root).expanduser().resolve())
        if self.posture_manifest is not None:
            object.__setattr__(self, "posture_manifest", Path(self.posture_manifest).expanduser().resolve())
        if self.epochs <= 0 or self.imgsz <= 0 or self.patience < 0 or self.workers < 0:
            raise ValueError("epochs/imgsz는 양수이고 patience/workers는 0 이상이어야 합니다")
        for field_name in ("min_mask_recall", "min_mask_map50"):
            value = getattr(self, field_name)
            if value < 0 or value > 1:
                raise ValueError(f"{field_name}는 0..1 범위여야 합니다")

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        for key in ("data", "run_root", "posture_manifest"):
            if values[key] is not None:
                values[key] = str(values[key])
        return values

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "TrainingConfig":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in values.items() if key in allowed})
