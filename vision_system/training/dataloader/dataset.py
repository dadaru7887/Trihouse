from dataclasses import dataclass
from pathlib import Path

from vision_system.training.dataloader.audit import DatasetReport, audit_dataset


@dataclass(frozen=True)
class DatasetLoader:
    data_yaml: Path
    allow_posture_gap: bool = True
    posture_manifest: Path | None = None
    min_fallen_per_eval_split: int = 10

    def validate(self, output_dir: Path) -> DatasetReport:
        return audit_dataset(
            self.data_yaml,
            output_dir,
            posture_manifest=self.posture_manifest,
            allow_posture_gap=self.allow_posture_gap,
            min_fallen_per_eval_split=self.min_fallen_per_eval_split,
        )
