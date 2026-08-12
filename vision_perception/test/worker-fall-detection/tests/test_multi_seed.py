import json
import math
from pathlib import Path

from pipeline.multi_seed import aggregate_seed_runs, build_seed_command, select_deployment_model


def make_run(root: Path, seed: int, val: dict, test: dict) -> Path:
    run = root / f"seed_{seed}"
    (run / "evaluation").mkdir(parents=True)
    (run / "train/weights").mkdir(parents=True)
    (run / "train/weights/best.pt").write_bytes(str(seed).encode())
    (run / "evaluation/validation_metrics.json").write_text(json.dumps(val))
    (run / "evaluation/test_metrics.json").write_text(json.dumps(test))
    (run / "status.json").write_text(json.dumps({"state": "COMPLETED"}))
    (run / "artifact_manifest.json").write_text(json.dumps({"dataset_fingerprint": "abc"}))
    return run


def test_seed_command_sets_pythonhashseed_and_uses_separate_run(tmp_path: Path) -> None:
    command, environment = build_seed_command(
        python=Path("/venv/bin/python"), runner=Path("train_seed.py"),
        config=Path("config.yaml"), seed=42, experiment_dir=tmp_path,
        base_environment={"PATH": "/bin"},
    )
    assert command == ["/venv/bin/python", "train_seed.py", "--config", "config.yaml", "--seed", "42", "--experiment-dir", str(tmp_path)]
    assert environment["PYTHONHASHSEED"] == "42"
    assert environment["PATH"] == "/bin"


def test_aggregate_reports_all_seed_test_mean_and_sample_std(tmp_path: Path) -> None:
    make_run(tmp_path, 17, {"mask_map50_95": 0.7, "mask_recall": 0.8}, {"mask_recall": 0.8, "mask_map50_95": 0.6})
    make_run(tmp_path, 42, {"mask_map50_95": 0.8, "mask_recall": 0.75}, {"mask_recall": 1.0, "mask_map50_95": 0.8})

    aggregate = aggregate_seed_runs(tmp_path, [17, 42])

    assert aggregate["successful_seeds"] == [17, 42]
    assert aggregate["test_summary"]["mask_recall"]["mean"] == 0.9
    assert math.isclose(aggregate["test_summary"]["mask_recall"]["std"], math.sqrt(0.02))
    assert aggregate["test_summary"]["mask_recall"]["min"] == 0.8
    assert aggregate["test_summary"]["mask_recall"]["max"] == 1.0


def test_model_selection_uses_validation_only_and_deterministic_tie_break(tmp_path: Path) -> None:
    # Seed 17 has much better test metrics, but seed 42 wins on validation.
    make_run(tmp_path, 17, {"mask_map50_95": 0.7, "mask_recall": 0.99}, {"mask_map50_95": 1.0})
    make_run(tmp_path, 42, {"mask_map50_95": 0.8, "mask_recall": 0.8}, {"mask_map50_95": 0.1})
    selected = select_deployment_model(tmp_path, [17, 42], "mask_map50_95", "mask_recall")
    assert selected["selected_seed"] == 42
    assert selected["selection"]["split"] == "validation"
    assert selected["test_metrics_used_for_selection"] is False

    # Exact validation tie selects the lower seed.
    (tmp_path / "seed_17/evaluation/validation_metrics.json").write_text(json.dumps({"mask_map50_95": 0.8, "mask_recall": 0.8}))
    selected = select_deployment_model(tmp_path, [42, 17], "mask_map50_95", "mask_recall")
    assert selected["selected_seed"] == 17
