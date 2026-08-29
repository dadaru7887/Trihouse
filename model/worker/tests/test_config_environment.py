import json
from pathlib import Path

import pytest
import yaml

from model.perception.segmentation.training.config_loader import ConfigError, load_experiment_config
from model.perception.segmentation.training.environment import EnvironmentError, capture_environment, validate_training_environment


def write_config(path: Path, updates=None) -> Path:
    config = {
        "schema_version": 1,
        "experiment": {"name": "multi", "seeds": [17, 42], "continue_on_failure": True},
        "dataset": {"data_yaml": "dataset/data.yaml", "allow_posture_gap": True, "min_fallen_per_eval_split": 10},
        "model": {"weights": "26s", "image_size": 640},
        "training": {"epochs": 20, "patience": 5, "batch": -1, "workers": 4, "device": "0", "augmentation": True, "augmentation_seed": 42, "deterministic": True},
        "evaluation": {"min_mask_recall": 0.9, "min_mask_map50": 0.8},
        "output": {"run_root": "runs/lego"},
        "selection": {"metric": "mask_map50_95", "tie_breaker": "mask_recall"},
    }
    if updates:
        config.update(updates)
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def test_config_loads_strict_schema_and_resolves_project_paths(tmp_path: Path) -> None:
    (tmp_path / "dataset").mkdir()
    (tmp_path / "dataset/data.yaml").write_text("names: [person]\n")
    loaded = load_experiment_config(write_config(tmp_path / "config.yaml"), project_root=tmp_path)
    assert loaded.name == "multi"
    assert loaded.seeds == (17, 42)
    assert loaded.training.data == (tmp_path / "dataset/data.yaml").resolve()
    assert loaded.training.run_root == (tmp_path / "runs/lego/multi").resolve()
    assert loaded.training.deterministic is True
    assert loaded.training.augmentation_seed == 42
    assert loaded.training.seed == 17


def test_config_rejects_unknown_keys(tmp_path: Path) -> None:
    path = write_config(tmp_path / "config.yaml", {"mystery": {"enabled": True}})
    with pytest.raises(ConfigError, match="알 수 없는 key.*mystery"):
        load_experiment_config(path, project_root=tmp_path)


def test_config_rejects_duplicate_or_non_integer_seeds(tmp_path: Path) -> None:
    path = write_config(tmp_path / "config.yaml", {"experiment": {"name": "x", "seeds": [42, 42], "continue_on_failure": True}})
    with pytest.raises(ConfigError, match="seed"):
        load_experiment_config(path, project_root=tmp_path)


class FakeTorch:
    __version__ = "2.7.1+cu128"
    version = type("Version", (), {"cuda": "12.8"})()
    backends = type("Backends", (), {"cudnn": type("Cudnn", (), {"version": staticmethod(lambda: 90501)})()})()
    cuda = type("Cuda", (), {
        "is_available": staticmethod(lambda: True),
        "get_device_name": staticmethod(lambda index: "NVIDIA GeForce RTX 5080"),
        "get_device_capability": staticmethod(lambda index: (12, 0)),
        "get_arch_list": staticmethod(lambda: ["sm_80", "sm_120"]),
    })()


def test_environment_snapshot_records_reproducibility_fields(tmp_path: Path) -> None:
    snapshot = capture_environment(
        dataset_fingerprint="abc", torch_module=FakeTorch,
        package_versions={"ultralytics": "8.4.0", "albumentations": "1.4.6"},
        git_info={"sha": "deadbeef", "dirty": False},
        nvidia_info={"driver_version": "580.1", "driver_cuda": "13.0"},
    )
    validate_training_environment(snapshot, require_cuda=True)
    assert snapshot["gpu"]["compute_capability"] == "12.0"
    assert snapshot["pytorch"]["cuda_runtime"] == "12.8"
    assert snapshot["pytorch"]["supported_arches"][-1] == "sm_120"
    assert snapshot["dataset"]["fingerprint"] == "abc"
    assert snapshot["git"]["sha"] == "deadbeef"


def test_environment_gate_rejects_rtx5080_without_sm120() -> None:
    snapshot = capture_environment(
        dataset_fingerprint="abc", torch_module=FakeTorch,
        package_versions={}, git_info={}, nvidia_info={},
    )
    snapshot["pytorch"]["supported_arches"] = ["sm_90"]
    with pytest.raises(EnvironmentError, match="sm_120"):
        validate_training_environment(snapshot, require_cuda=True)


def test_environment_snapshot_records_selected_gpu_index() -> None:
    seen = []
    cuda = type("Cuda", (), {
        "is_available": staticmethod(lambda: True),
        "get_device_name": staticmethod(lambda index: seen.append(index) or f"GPU {index}"),
        "get_device_capability": staticmethod(lambda index: (8, index)),
        "get_arch_list": staticmethod(lambda: ["sm_80"]),
    })()
    torch_module = type("Torch", (), {
        "__version__": "2.7.1", "version": type("Version", (), {"cuda": "12.8"})(),
        "backends": FakeTorch.backends, "cuda": cuda,
    })()
    snapshot = capture_environment("abc", torch_module=torch_module, package_versions={}, git_info={}, nvidia_info={}, gpu_index=1)
    assert seen == [1]
    assert snapshot["gpu"]["index"] == 1
    assert snapshot["gpu"]["name"] == "GPU 1"


# ---------------------------------------- 데이터셋 경로는 하이퍼파라미터다


def _config_yaml(tmp_path, data_yaml: str) -> "Path":
    from pathlib import Path

    text = f"""
schema_version: 1
experiment: {{name: t, seeds: [42], continue_on_failure: true}}
dataset: {{data_yaml: {data_yaml}, allow_posture_gap: true}}
model: {{weights: 26s, image_size: 640}}
training: {{epochs: 1, patience: 1, batch: -1, workers: 0, device: cpu}}
evaluation: {{min_mask_recall: 0.1, min_mask_map50: 0.1}}
output: {{run_root: runs/t}}
selection: {{metric: person_mask_map50_95, tie_breaker: person_mask_recall}}
"""
    path = Path(tmp_path) / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_config_dataset_path_can_be_overridden(tmp_path) -> None:
    """데이터셋 경로는 코드도 config 도 아닌 **인자**로 정해질 수 있어야 한다."""
    from model.perception.segmentation.training.config_loader import load_experiment_config

    path = _config_yaml(tmp_path, "placeholder/data.yaml")
    overridden = load_experiment_config(path, data_override=tmp_path / "other" / "data.yaml")

    assert overridden.training.data == (tmp_path / "other" / "data.yaml").resolve()


def test_without_an_override_the_config_value_is_used(tmp_path) -> None:
    from model.perception.segmentation.training.config_loader import load_experiment_config

    path = _config_yaml(tmp_path, "placeholder/data.yaml")
    config = load_experiment_config(path)

    assert config.training.data.name == "data.yaml"
    assert "placeholder" in str(config.training.data)


def test_the_shipped_config_ships_a_placeholder_not_a_real_path() -> None:
    """저장소에 딸려 오는 config 가 실재하지 않는 경로를 실재하는 척 가리키면 안 된다."""
    import yaml
    from pathlib import Path

    raw = yaml.safe_load(
        Path("model/perception/segmentation/training/configs/config.yaml").read_text(encoding="utf-8")
    )
    value = raw["dataset"]["data_yaml"]

    assert "PLACEHOLDER" in value or "<" in value
