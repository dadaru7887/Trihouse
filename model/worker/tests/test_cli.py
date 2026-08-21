import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml


TRAIN_MODULE = "model.perception.segmentation.training.train"
REPOSITORY = Path(__file__).resolve().parents[3]


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


def run(stage: str, *args: str) -> subprocess.CompletedProcess[str]:
    """학습 진입점을 **모듈로** 부른다.

    스크립트 경로로 부르면 이 테스트가 소스 배치를 알아야 하고, 폴더를 옮길
    때마다 같이 고쳐야 한다. 실제 사용자도 `python -m` 으로 부른다.
    """
    return subprocess.run(
        [sys.executable, "-m", TRAIN_MODULE, stage, *args],
        text=True, capture_output=True, cwd=REPOSITORY,
    )


def test_every_stage_has_dependency_light_help() -> None:
    """`--help` 조차 ultralytics 를 끌어오면 GPU 없는 곳에서 도구가 안 뜬다."""
    for stage in ("labels", "preflight", "run", "train", "evaluate", "analyze"):
        result = run(stage, "--help")
        assert result.returncode == 0, (stage, result.stderr)
        assert "usage:" in result.stdout


def test_preflight_refuses_posture_gap_without_override(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")
    result = run("preflight", "--data", str(data), "--output", str(tmp_path / "run"))
    assert result.returncode == 2
    assert "allow-posture-gap" in result.stderr


def test_preflight_override_writes_reusable_config(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")
    run_dir = tmp_path / "run"
    result = run(
        "preflight", "--data", str(data), "--output", str(run_dir),
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
        "run", "--data", str(data), "--run-root", str(tmp_path / "runs"),
        "--name", "smoke", "--allow-posture-gap", "--preflight-only",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "runs/smoke/status.json").is_file()


def test_all_in_one_checks_dataset_gate_before_importing_ultralytics(tmp_path: Path) -> None:
    data = make_dataset(tmp_path / "dataset")
    result = run(
        "run", "--data", str(data), "--run-root", str(tmp_path / "runs"),
        "--name", "blocked",
    )
    assert result.returncode == 2
    assert "allow-posture-gap" in result.stderr
    assert "ultralytics" not in result.stderr
