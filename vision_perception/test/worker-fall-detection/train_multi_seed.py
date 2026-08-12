import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from pipeline.config_loader import load_experiment_config
from pipeline.dataset_audit import audit_dataset
from pipeline.device import resolve_device
from pipeline.environment import capture_environment, validate_training_environment, write_environment
from pipeline.multi_seed import aggregate_seed_runs, build_seed_command, select_deployment_model, write_experiment_reports


def main() -> None:
    parser = argparse.ArgumentParser(description="격리 subprocess 기반 multi-seed YOLOE 학습")
    parser.add_argument("--config", type=Path, default=Path(__file__).parent / "configs/config.yaml")
    parser.add_argument("--experiment-dir", type=Path)
    args = parser.parse_args()
    experiment = load_experiment_config(args.config)
    root = args.experiment_dir or experiment.training.run_root / datetime.now().strftime("%Y%m%d_%H%M%S")
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / "experiment.json").write_text(json.dumps({"config": str(experiment.config_path), "seeds": experiment.seeds}, indent=2) + "\n")
    report = audit_dataset(
        experiment.training.data, root / "preflight",
        posture_manifest=experiment.training.posture_manifest,
        allow_posture_gap=experiment.training.allow_posture_gap,
        min_fallen_per_eval_split=experiment.training.min_fallen_per_eval_split,
    )
    environment_snapshot = capture_environment(report.fingerprint)
    device_selection = resolve_device(experiment.training.device)
    environment_snapshot["device"] = device_selection.to_dict()
    write_environment(root / "environment.json", environment_snapshot)
    validate_training_environment(environment_snapshot, require_cuda=device_selection.requires_cuda)
    runner = Path(__file__).parent / "train_seed.py"
    failures = []
    for seed in experiment.seeds:
        command, environment = build_seed_command(Path(sys.executable), runner, experiment.config_path, seed, root, os.environ)
        result = subprocess.run(command, env=environment, check=False)
        if result.returncode:
            failures.append(seed)
            if not experiment.continue_on_failure:
                raise SystemExit(result.returncode)
    aggregate = aggregate_seed_runs(root, list(experiment.seeds))
    if not aggregate["successful_seeds"]:
        raise SystemExit(f"성공한 seed가 없습니다. 실패: {failures}")
    selected = select_deployment_model(root, aggregate["successful_seeds"], experiment.selection_metric, experiment.selection_tie_breaker)
    write_experiment_reports(root, aggregate, selected)
    print(root / "selected_model.json")


if __name__ == "__main__":
    main()
