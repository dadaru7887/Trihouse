import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from vision_ai.data_loader.perception.dataset import DatasetLoader
from vision_ai.utils.config_loader import ExperimentConfig, load_experiment_config
from vision_ai.utils.device import resolve_device
from vision_ai.utils.environment import capture_environment, validate_training_environment, write_environment
from vision_ai.models.perception.trainer.multi_seed import aggregate_seed_runs, build_seed_command, select_deployment_model, write_experiment_reports


@dataclass
class MultiSeedExperiment:
    config: ExperimentConfig
    experiment_dir: Path
    # 부모가 --data 로 덮어썼으면 seed 자식들에게도 같은 값을 넘겨야 한다.
    data_override: Path | None = None

    @classmethod
    def from_config(cls, config_path: Path, experiment_dir: Path | None = None,
                    data_override: Path | None = None):
        config = load_experiment_config(config_path, data_override=data_override)
        run_dir = experiment_dir or config.training.run_root / datetime.now().strftime("%Y%m%d_%H%M%S")
        return cls(config=config, experiment_dir=Path(run_dir).resolve(),
                   data_override=Path(data_override).resolve() if data_override else None)

    def _write_metadata(self) -> None:
        metadata = {
            "config": str(self.config.config_path),
            "seeds": {"training": self.config.seeds, "augmentation": self.config.training.augmentation_seed},
            "experiment_type": "fixed_augmentation_seed_training_seed_sensitivity",
        }
        (self.experiment_dir / "experiment.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    def _preflight(self) -> None:
        report = DatasetLoader(
            data_yaml=self.config.training.data,
            allow_posture_gap=self.config.training.allow_posture_gap,
            posture_manifest=self.config.training.posture_manifest,
            min_fallen_per_eval_split=self.config.training.min_fallen_per_eval_split,
        ).validate(self.experiment_dir / "preflight")
        device = resolve_device(self.config.training.device)
        gpu_index = int(device.resolved) if device.requires_cuda else 0
        environment = capture_environment(report.fingerprint, gpu_index=gpu_index)
        environment["device"] = device.to_dict()
        write_environment(self.experiment_dir / "environment.json", environment)
        validate_training_environment(environment, require_cuda=device.requires_cuda)

    def _run_seeds(self) -> list[int]:
        failures = []
        for seed in self.config.seeds:
            command, environment = build_seed_command(
                Path(sys.executable), self.config.config_path, seed, self.experiment_dir,
                os.environ, data_override=self.data_override,
            )
            result = subprocess.run(command, env=environment, check=False)
            if result.returncode:
                failures.append(seed)
                if not self.config.continue_on_failure:
                    raise RuntimeError(f"seed {seed} 학습 실패: exit={result.returncode}")
        return failures

    def run(self) -> Path:
        self.experiment_dir.mkdir(parents=True, exist_ok=False)
        self._write_metadata()
        self._preflight()
        failures = self._run_seeds()
        aggregate = aggregate_seed_runs(self.experiment_dir, list(self.config.seeds))
        if not aggregate["successful_seeds"]:
            raise RuntimeError(f"성공한 seed가 없습니다. 실패: {failures}")
        selected = select_deployment_model(
            self.experiment_dir, aggregate["successful_seeds"],
            self.config.selection_metric, self.config.selection_tie_breaker,
        )
        write_experiment_reports(self.experiment_dir, aggregate, selected)
        from vision_ai.visualization.report import analyze_experiment
        analyze_experiment(self.experiment_dir)
        return self.experiment_dir / "selected_model.json"
