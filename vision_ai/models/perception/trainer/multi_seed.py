import csv
import json
import statistics
from pathlib import Path
from typing import Mapping


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


SEED_RUNNER_MODULE = "vision_ai.models.perception.trainer.seed_runner"


def build_seed_command(
    python: Path,
    config: Path,
    seed: int,
    experiment_dir: Path,
    base_environment: Mapping[str, str],
    runner_module: str = SEED_RUNNER_MODULE,
    data_override: Path | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Build the child-process command that runs one seed.

    Invoked as `-m <module>` rather than a script path: a path would make the
    experiment depend on where its own source lives, which breaks silently as
    soon as a folder moves.
    """
    command = [
        str(python), "-m", runner_module, "--config", str(config), "--seed", str(seed),
        "--experiment-dir", str(experiment_dir),
    ]
    if data_override is not None:
        command += ["--data", str(data_override)]
    environment = dict(base_environment)
    environment["PYTHONHASHSEED"] = str(seed)
    environment["NO_ALBUMENTATIONS_UPDATE"] = "1"
    return command, environment


def _successful_run(experiment_dir: Path, seed: int) -> Path | None:
    run_dir = experiment_dir / f"seed_{seed}"
    status_path = run_dir / "status.json"
    test_path = run_dir / "evaluation/test_metrics.json"
    if not status_path.is_file() or not test_path.is_file():
        return None
    if _read_json(status_path).get("state") != "COMPLETED":
        return None
    return run_dir


def aggregate_seed_runs(experiment_dir: Path, seeds: list[int]) -> dict:
    per_seed = []
    for seed in sorted(set(seeds)):
        run_dir = _successful_run(experiment_dir, seed)
        if run_dir is None:
            continue
        per_seed.append({"seed": seed, "test": _read_json(run_dir / "evaluation/test_metrics.json")})

    metric_names = sorted({name for row in per_seed for name, value in row["test"].items() if isinstance(value, (int, float))})
    summary = {}
    for name in metric_names:
        values = [float(row["test"][name]) for row in per_seed if isinstance(row["test"].get(name), (int, float))]
        summary[name] = {
            "mean": statistics.mean(values),
            "std": statistics.stdev(values) if len(values) > 1 else 0.0,
            "min": min(values),
            "max": max(values),
            "count": len(values),
        }
    return {
        "schema_version": 1,
        "successful_seeds": [row["seed"] for row in per_seed],
        "failed_seeds": sorted(set(seeds) - {row["seed"] for row in per_seed}),
        "per_seed": per_seed,
        "test_summary": summary,
    }


def select_deployment_model(
    experiment_dir: Path,
    seeds: list[int],
    primary_metric: str,
    tie_breaker_metric: str,
) -> dict:
    candidates = []
    for seed in sorted(set(seeds)):
        run_dir = _successful_run(experiment_dir, seed)
        if run_dir is None:
            continue
        validation = _read_json(run_dir / "evaluation/validation_metrics.json")
        manifest = _read_json(run_dir / "artifact_manifest.json")
        if manifest.get("validation_gate_passed") is False:
            continue
        if primary_metric not in validation or tie_breaker_metric not in validation:
            continue
        candidates.append((float(validation[primary_metric]), float(validation[tie_breaker_metric]), seed, run_dir, validation))
    if not candidates:
        raise ValueError("no successful seed has validation metrics")
    primary, tie_breaker, seed, run_dir, validation = min(
        candidates, key=lambda row: (-row[0], -row[1], row[2])
    )
    manifest = _read_json(run_dir / "artifact_manifest.json")
    return {
        "schema_version": 1,
        "selected_seed": seed,
        "weights": str((run_dir / "train/weights/best.pt").resolve()),
        "dataset_fingerprint": manifest.get("dataset_fingerprint"),
        "seeds": manifest.get("seeds", {"training": seed}),
        "selection": {
            "split": "validation",
            "primary_metric": primary_metric,
            "primary_value": primary,
            "tie_breaker_metric": tie_breaker_metric,
            "tie_breaker_value": tie_breaker,
            "final_tie_breaker": "lowest_seed",
            "validation_metrics": validation,
        },
        "test_metrics_used_for_selection": False,
        "rationale": "compares validation only; test results never pick the representative model",
    }


def write_experiment_reports(experiment_dir: Path, aggregate: dict, selected: dict) -> None:
    experiment_dir.mkdir(parents=True, exist_ok=True)
    (experiment_dir / "aggregate.json").write_text(json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (experiment_dir / "selected_model.json").write_text(json.dumps(selected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with (experiment_dir / "seed_results.csv").open("w", newline="", encoding="utf-8") as stream:
        names = sorted({name for row in aggregate["per_seed"] for name in row["test"]})
        writer = csv.DictWriter(stream, fieldnames=["seed", *names])
        writer.writeheader()
        for row in aggregate["per_seed"]:
            writer.writerow({"seed": row["seed"], **row["test"]})

    with (experiment_dir / "test_summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["metric", "mean", "std", "min", "max", "count"])
        writer.writeheader()
        for metric, values in aggregate["test_summary"].items():
            writer.writerow({"metric": metric, **values})

    lines = ["# Multi-seed test summary", "", "| metric | mean ± std | min | max | n |", "|---|---:|---:|---:|---:|"]
    for metric, values in aggregate["test_summary"].items():
        lines.append(f"| {metric} | {values['mean']:.6f} ± {values['std']:.6f} | {values['min']:.6f} | {values['max']:.6f} | {values['count']} |")
    (experiment_dir / "test_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
