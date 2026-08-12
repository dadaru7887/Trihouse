import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml


ROOT = Path(__file__).resolve().parents[1]


def make_dataset(root: Path) -> Path:
    for index, split in enumerate(("train", "valid", "test")):
        (root / split / "images").mkdir(parents=True)
        (root / split / "labels").mkdir(parents=True)
        cv2.imwrite(str(root / split / "images" / f"{split}.jpg"), np.full((8, 8, 3), index + 5))
        (root / split / "labels" / f"{split}.txt").write_text(
            "1 0.1 0.1 0.8 0.1 0.8 0.8 0.1 0.8\n", encoding="utf-8"
        )
    data = {"train": "train/images", "val": "valid/images", "test": "test/images", "nc": 2, "names": ["obstacle", "person"]}
    path = root / "data.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / script), *args], text=True, capture_output=True
    )


def test_all_python_entrypoints_have_dependency_light_help() -> None:
    for script in ("preflight.py", "train_stage.py", "evaluate_stage.py", "run_pipeline.py"):
        result = run(script, "--help")
        assert result.returncode == 0, (script, result.stderr)
        assert "usage:" in result.stdout


def test_preflight_refuses_posture_gap_without_override(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")
    result = run("preflight.py", "--data", str(data), "--output", str(tmp_path / "run"))
    assert result.returncode == 2
    assert "allow-posture-gap" in result.stderr


def test_preflight_override_writes_reusable_config(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")
    run_dir = tmp_path / "run"
    result = run(
        "preflight.py", "--data", str(data), "--output", str(run_dir),
        "--allow-posture-gap", "--model", "26s", "--epochs", "3",
    )
    assert result.returncode == 0, result.stderr
    resolved = json.loads((run_dir / "config/resolved.json").read_text())
    assert resolved["model"] == "26s"
    assert resolved["epochs"] == 3
    assert resolved["allow_posture_gap"] is True
    assert (run_dir / "preflight/dataset_report.json").is_file()


def test_all_in_one_preflight_only_does_not_import_ultralytics(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")
    result = run(
        "run_pipeline.py", "--data", str(data), "--run-root", str(tmp_path / "runs"),
        "--name", "smoke", "--allow-posture-gap", "--preflight-only",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "runs/smoke/status.json").is_file()


def test_all_in_one_checks_dataset_gate_before_importing_ultralytics(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")
    result = run(
        "run_pipeline.py", "--data", str(data), "--run-root", str(tmp_path / "runs"),
        "--name", "blocked",
    )
    assert result.returncode == 2
    assert "allow-posture-gap" in result.stderr
    assert "ultralytics" not in result.stderr
