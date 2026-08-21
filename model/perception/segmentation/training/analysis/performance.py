import json
from pathlib import Path

import pandas as pd


def _metrics(path: Path, prefix: str) -> dict:
    if not path.is_file():
        return {}
    return {f"{prefix}_{key}": value for key, value in json.loads(path.read_text(encoding="utf-8")).items() if isinstance(value, (int, float))}


def _last_training_metrics(path: Path) -> dict:
    if not path.is_file():
        return {}
    frame = pd.read_csv(path); frame.columns = [column.strip() for column in frame.columns]
    if frame.empty:
        return {}
    last = frame.iloc[-1]
    values = {}
    for column in frame.columns:
        if column == "epoch" or not pd.api.types.is_numeric_dtype(frame[column]):
            continue
        safe = column.lower().replace("/", "_").replace("(", "").replace(")", "")
        values[f"final_{safe}"] = float(last[column])
    return values


def build_seed_performance_table(experiment_dir: Path) -> pd.DataFrame:
    rows = []
    for run in sorted(Path(experiment_dir).glob("seed_*"), key=lambda path: int(path.name.split("_")[-1])):
        seed = int(run.name.split("_")[-1])
        rows.append({"seed": seed, **_metrics(run / "evaluation/validation_metrics.json", "validation"), **_metrics(run / "evaluation/test_metrics.json", "test"), **_last_training_metrics(run / "train/results.csv")})
    return pd.DataFrame(rows)


def diagnose_training_run(frame: pd.DataFrame, plateau_epochs: int = 10) -> dict:
    frame = frame.copy(); frame.columns = [column.strip() for column in frame.columns]
    warnings = []
    metric = next((name for name in ("metrics/mAP50(M)", "metrics/mAP50-95(M)", "metrics/mAP50(B)") if name in frame), None)
    if metric and len(frame) >= plateau_epochs + 1:
        recent = frame[metric].tail(plateau_epochs)
        if float(recent.max() - recent.min()) < 0.01:
            warnings.append("metric_plateau")
    if "val/seg_loss" in frame and len(frame) >= 4 and frame["val/seg_loss"].tail(4).is_monotonic_increasing:
        warnings.append("validation_loss_rising")
    return {"epochs": len(frame), "warnings": warnings}
