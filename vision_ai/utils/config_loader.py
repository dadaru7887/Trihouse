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
        raise ConfigError(f"{key}는 mapping이어야 합니다")
    unknown = set(value) - SECTION_KEYS[key]
    if unknown:
        raise ConfigError(f"알 수 없는 key: {key}.{sorted(unknown)[0]}")
    return value


def _resolve(root: Path, value: str | None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


# config 안의 상대 경로가 무엇을 기준으로 하는가. **저장소 루트**다.
#
# 전에는 config 파일 위치에서 `path.parents[4]` 로 거슬러 올라갔다. 그러면 config
# 를 다른 깊이로 옮기는 순간 조용히 엉뚱한 곳을 가리킨다 — 오류가 아니라 "데이터가
# 없다" 로 나타나서 원인에서 멀다. 여기서는 이 모듈의 위치로 루트를 잡는다.
# `vision_ai/utils/config_loader.py` -> parents[4] 가 저장소 루트다.
# 저장소 밖의 config 를 쓰려면 `project_root` 를 명시적으로 넘긴다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def load_experiment_config(
    path: Path | str,
    project_root: Path | str | None = None,
    data_override: Path | str | None = None,
) -> ExperimentConfig:
    """`data_override` 가 있으면 config 의 dataset.data_yaml 을 이긴다.

    데이터셋 경로는 실험마다 바뀌는 값이므로 config 파일을 고쳐 가며 쓰는 것이
    아니라 인자로 들어올 수 있어야 한다. 우선순위는 인자 > config > (기본값 없음).
    """
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ConfigError(f"config 파일이 없습니다: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("config 최상위 값은 mapping이어야 합니다")
    unknown = set(raw) - ROOT_KEYS
    if unknown:
        raise ConfigError(f"알 수 없는 key: {sorted(unknown)[0]}")
    if raw.get("schema_version") != 1:
        raise ConfigError("schema_version은 1이어야 합니다")
    sections = {name: _mapping(raw, name) for name in SECTION_KEYS}
    experiment = sections["experiment"]
    seeds = experiment.get("seeds")
    if not isinstance(seeds, list) or not seeds or any(type(seed) is not int for seed in seeds) or len(set(seeds)) != len(seeds):
        raise ConfigError("experiment.seeds는 중복 없는 정수 목록이어야 합니다")
    name = experiment.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError("experiment.name은 비어 있지 않은 문자열이어야 합니다")
    root = Path(project_root).resolve() if project_root else REPOSITORY_ROOT
    dataset, model, training, evaluation, output, selection = (
        sections[key] for key in ("dataset", "model", "training", "evaluation", "output", "selection")
    )
    data = _resolve(root, str(data_override) if data_override is not None
                    else dataset.get("data_yaml"))
    if data is None:
        raise ConfigError("dataset.data_yaml이 필요합니다 (또는 --data 로 넘기십시오)")
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
