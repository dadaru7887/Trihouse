from pathlib import Path


def build_training_command(python: Path, project_dir: Path, config: Path, experiment_dir: Path | None = None) -> list[str]:
    command = [str(python), str(project_dir / "main.py"), "train", "--config", str(config)]
    if experiment_dir: command.extend(("--experiment-dir", str(experiment_dir)))
    return command


training_command = build_training_command
