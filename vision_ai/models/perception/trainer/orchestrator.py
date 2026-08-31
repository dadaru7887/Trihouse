import dataclasses
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from vision_ai.data_loader.perception.audit import audit_dataset
from vision_ai.utils.device import resolve_device
from vision_ai.utils.environment import capture_environment, validate_training_environment, write_environment
from vision_ai.utils.run_logging import Tracker, setup_logging
from vision_ai.utils.run_config import TrainingConfig


class PipelineError(RuntimeError):
    """Raised when a pipeline quality or artifact gate fails."""


class TrainingBackend(Protocol):
    def train(self, config: TrainingConfig, run_dir: Path) -> Path: ...
    def evaluate(
        self, weights: Path, split: str, config: TrainingConfig, run_dir: Path
    ) -> dict[str, float]: ...


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _git_metadata() -> dict[str, object]:
    def run(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], check=True, capture_output=True, text=True
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return "unknown"
    return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain"))}


def _run_name(config: TrainingConfig) -> str:
    if config.name:
        return config.name
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    aug = "aug" if config.augmentation else "noaug"
    return f"{timestamp}_{Path(config.model).stem}_{aug}"


def _format_metrics(metrics: dict) -> str:
    """Render a metrics dict as one readable log line."""
    return " ".join(f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"
                    for k, v in sorted(metrics.items()))


def run_pipeline(config: TrainingConfig, backend: TrainingBackend) -> Path:
    run_dir = config.run_root / _run_name(config)
    if run_dir.exists() and any(run_dir.iterdir()):
        raise PipelineError(f"run 디렉터리가 이미 존재하고 비어 있지 않습니다: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    stage = "PREFLIGHT"
    started = datetime.now(timezone.utc).isoformat()
    logger = setup_logging(run_dir)
    logger.info("run %s | data=%s | seed=%s | augmentation=%s | holdout=%s",
                run_dir.name, config.data, config.seed, config.augmentation,
                ",".join(config.augmentation_holdout) or "none")
    _write_json(run_dir / "status.json", {"state": "RUNNING", "stage": stage, "started_at": started})
    tracker = Tracker(enabled=config.wandb, project=config.wandb_project,
                      name=run_dir.name, config=config.to_dict(), run_dir=run_dir)
    try:
        report = audit_dataset(
            config.data,
            run_dir / "preflight",
            posture_manifest=config.posture_manifest,
            allow_posture_gap=config.allow_posture_gap,
            min_fallen_per_eval_split=config.min_fallen_per_eval_split,
        )
        logger.info("PREFLIGHT ok | fingerprint=%s | person_class_id=%s",
                    report.fingerprint[:12], report.person_class_id)
        device_selection = resolve_device(config.device)
        logger.info("device %s -> %s (%s)", config.device,
                    device_selection.resolved, device_selection.reason)
        config = dataclasses.replace(config, device=device_selection.resolved)
        gpu_index = int(device_selection.resolved) if device_selection.requires_cuda else 0
        environment = capture_environment(report.fingerprint, gpu_index=gpu_index)
        environment["device"] = device_selection.to_dict()
        write_environment(run_dir / "environment.json", environment)
        if not config.preflight_only:
            validate_training_environment(environment, require_cuda=device_selection.requires_cuda)
        run_metadata = {
            "config": config.to_dict(),
            "dataset_fingerprint": report.fingerprint,
            "git": _git_metadata(),
            "runtime": {"python": sys.version.split()[0], "platform": platform.platform()},
            "environment": "environment.json",
            "started_at": started,
        }
        _write_json(run_dir / "config/run.json", run_metadata)
        _write_json(run_dir / "config/resolved.json", config.to_dict())
        if config.preflight_only:
            _write_json(run_dir / "status.json", {
                "state": "PREFLIGHT_COMPLETED", "stage": "PREFLIGHT",
                "started_at": started, "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            return run_dir

        stage = "TRAIN"
        _write_json(run_dir / "status.json", {"state": "RUNNING", "stage": stage, "started_at": started})
        logger.info("TRAIN start | model=%s | epochs=%s | imgsz=%s | batch=%s",
                    config.model, config.epochs, config.imgsz, config.batch)
        weights = backend.train(config, run_dir).resolve()
        logger.info("TRAIN done | weights=%s", weights)
        if not weights.is_file():
            raise PipelineError(f"학습 backend가 best.pt를 만들지 않았습니다: {weights}")

        stage = "VALIDATION"
        validation = backend.evaluate(weights, "val", config, run_dir)
        _write_json(run_dir / "evaluation/validation_metrics.json", validation)
        logger.info("VALIDATION %s", _format_metrics(validation))
        tracker.log({f"val/{k}": v for k, v in validation.items()})
        stage = "VALIDATION_GATE"
        gate_recall = validation.get("person_mask_recall", validation.get("mask_recall", -1.0))
        gate_map50 = validation.get("person_mask_map50", validation.get("mask_map50", -1.0))
        validation_gate_passed = not (
            gate_recall < config.min_mask_recall
            or gate_map50 < config.min_mask_map50
        )
        logger.info("VALIDATION_GATE %s | recall=%.4f (floor %.2f) map50=%.4f (floor %.2f)",
                    "passed" if validation_gate_passed else "FAILED",
                    gate_recall, config.min_mask_recall, gate_map50, config.min_mask_map50)
        if not validation_gate_passed and not config.test_on_validation_gate_failure:
            raise PipelineError(
                "validation gate 실패: "
                f"person_mask_recall={gate_recall}, person_mask_map50={gate_map50}"
            )

        stage = "TEST"
        test_metrics = backend.evaluate(weights, "test", config, run_dir)
        _write_json(run_dir / "evaluation/test_metrics.json", test_metrics)
        logger.info("TEST %s", _format_metrics(test_metrics))
        tracker.log({f"test/{k}": v for k, v in test_metrics.items()})
        tracker.summary({**{f"val/{k}": v for k, v in validation.items()},
                         **{f"test/{k}": v for k, v in test_metrics.items()},
                         "validation_gate_passed": validation_gate_passed})
        manifest = {
            "schema_version": 1,
            "weights": str(weights),
            "dataset_fingerprint": report.fingerprint,
            "model": {"class_id": report.person_class_id, "class_name": "person", "imgsz": config.imgsz},
            "metrics": {
                "validation": "evaluation/validation_metrics.json",
                "test": "evaluation/test_metrics.json",
            },
            "validation_gate_passed": validation_gate_passed,
            "seeds": {"training": config.seed, "augmentation": config.augmentation_seed},
        }
        _write_json(run_dir / "artifact_manifest.json", manifest)
        _write_json(run_dir / "status.json", {
            "state": "COMPLETED", "stage": "COMPLETE", "started_at": started,
            "validation_gate_passed": validation_gate_passed,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("COMPLETE | %s", run_dir)
        return run_dir
    except Exception as error:
        _write_json(run_dir / "status.json", {
            "state": "FAILED", "stage": stage, "error": str(error), "started_at": started,
            "failed_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.error("FAILED at %s | %s", stage, error)
        raise
    finally:
        tracker.finish()
