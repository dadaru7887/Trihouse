import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .run_config import TrainingConfig


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    seeds: tuple[int, ...]
    continue_on_failure: bool
    training: TrainingConfig
    selection_metric: str
    selection_tie_breaker: str
    config_path: Path


ROOT_KEYS = {"schema_version", "experiment", "dataset", "model", "training", "evaluation", "output", "selection"}
SECTION_KEYS = {
    "experiment": {"name", "seeds", "continue_on_failure"},
    "dataset": {"data_yaml", "posture_manifest", "allow_posture_gap", "min_fallen_per_eval_split"},
    "model": {"weights", "image_size"},
    "training": {"epochs", "patience", "batch", "workers", "device", "augmentation", "augmentation_seed", "augmentation_source", "deterministic"},
    "evaluation": {"min_mask_recall", "min_mask_map50", "test_all_seeds"},
    "output": {"run_root"},
    "selection": {"metric", "tie_breaker"},
}


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{key} must be a mapping")
    unknown = set(value) - SECTION_KEYS[key]
    if unknown:
        raise ConfigError(f"unknown key: {key}.{sorted(unknown)[0]}")
    return value


def _resolve(root: Path, value: str | None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


# What a relative path inside a config is relative to: the repo root.
#
# Derived from this module's own location, not the config file's: walking up
# from the config would point somewhere else as soon as a config moves to a
# different depth, and that shows up as "no data" rather than an error.
# vision_ai/utils/config_loader.py -> parents[4] is the repo root.
# Pass `project_root` explicitly for a config kept outside the repo.
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def load_experiment_config(
    path: Path | str,
    project_root: Path | str | None = None,
    data_override: Path | str | None = None,
) -> ExperimentConfig:
    """Load a config; `data_override` beats the config's dataset.data_yaml.

    The dataset path changes per experiment, so it must be passable as an
    argument instead of by editing the file. Priority: argument > config, with
    no default.
    """
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("the top level of a config must be a mapping")
    unknown = set(raw) - ROOT_KEYS
    if unknown:
        raise ConfigError(f"unknown key: {sorted(unknown)[0]}")
    if raw.get("schema_version") != 1:
        raise ConfigError("schema_version must be 1")
    sections = {name: _mapping(raw, name) for name in SECTION_KEYS}
    experiment = sections["experiment"]
    seeds = experiment.get("seeds")
    if not isinstance(seeds, list) or not seeds or any(type(seed) is not int for seed in seeds) or len(set(seeds)) != len(seeds):
        raise ConfigError("experiment.seeds must be a list of distinct integers")
    name = experiment.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError("experiment.name must be a non-empty string")
    root = Path(project_root).resolve() if project_root else REPOSITORY_ROOT
    dataset, model, training, evaluation, output, selection = (
        sections[key] for key in ("dataset", "model", "training", "evaluation", "output", "selection")
    )
    data = _resolve(root, str(data_override) if data_override is not None
                    else dataset.get("data_yaml"))
    if data is None:
        raise ConfigError("dataset.data_yaml is required (or pass --data)")
    run_base = _resolve(root, output.get("run_root", "runs/lego_worker"))
    config = TrainingConfig(
        model=str(model.get("weights", "yoloe-26s-seg.pt")), data=data, run_root=run_base / name,
        augmentation=bool(training.get("augmentation", True)), epochs=int(training.get("epochs", 200)),
        augmentation_seed=int(training.get("augmentation_seed", 42)),
        imgsz=int(model.get("image_size", 640)), patience=int(training.get("patience", 20)),
        batch=int(training.get("batch", -1)), device=str(training.get("device", "auto")),
        workers=int(training.get("workers", 8)), seed=seeds[0],
        deterministic=bool(training.get("deterministic", True)),
        posture_manifest=_resolve(root, dataset.get("posture_manifest")),
        augmentation_source=_resolve(root, training.get("augmentation_source")),
        allow_posture_gap=bool(dataset.get("allow_posture_gap", False)),
        min_fallen_per_eval_split=int(dataset.get("min_fallen_per_eval_split", 10)),
        min_mask_recall=float(evaluation.get("min_mask_recall", 0.9)),
        min_mask_map50=float(evaluation.get("min_mask_map50", 0.8)),
        test_on_validation_gate_failure=bool(evaluation.get("test_all_seeds", False)),
    )
    return ExperimentConfig(
        name=name, seeds=tuple(seeds),
        continue_on_failure=bool(experiment.get("continue_on_failure", False)),
        training=config, selection_metric=str(selection.get("metric", "mask_map50_95")),
        selection_tie_breaker=str(selection.get("tie_breaker", "mask_recall")), config_path=path,
    )


def config_for_seed(experiment: ExperimentConfig, seed: int, name: str | None = None) -> TrainingConfig:
    return dataclasses.replace(experiment.training, seed=seed, name=name or f"seed_{seed}")
