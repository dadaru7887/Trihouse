from pathlib import Path

from vision_ai.models.perception.trainer.pipeline import build_parser
from vision_ai.models.perception.trainer.multi_seed_trainer import build_training_command


def test_main_parser_exposes_ml_workflow_stages() -> None:
    parser = build_parser()
    assert parser.parse_args(["labels"]).stage == "labels"
    assert parser.parse_args(["train"]).stage == "train"
    assert parser.parse_args(["analyze", "--experiment-dir", "/tmp/run"]).stage == "analyze"


def test_legacy_training_command_targets_main_train_stage() -> None:
    command = build_training_command(
        python=Path("/venv/python"), project_dir=Path("/project"),
        config=Path("config.yaml"), experiment_dir=Path("/runs/exp"),
    )
    assert command == [
        "/venv/python", "/project/main.py", "train", "--config", "config.yaml",
        "--experiment-dir", "/runs/exp",
    ]
