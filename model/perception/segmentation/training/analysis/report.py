import json
from pathlib import Path

import pandas as pd

from .performance import build_seed_performance_table, diagnose_training_run
from .visualization import save_seed_dashboard, save_training_curves


def _markdown_table(table: pd.DataFrame) -> list[str]:
    columns = list(table.columns)
    rows = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for _, row in table.iterrows():
        values = [f"{row[name]:.4f}" if isinstance(row[name], float) else str(row[name]) for name in columns]
        rows.append("| " + " | ".join(values) + " |")
    return rows


def _add_f1(table: pd.DataFrame, split: str) -> None:
    for prefix in ("person_mask", "mask"):
        precision, recall = f"{split}_{prefix}_precision", f"{split}_{prefix}_recall"
        if precision in table and recall in table:
            denominator = table[precision] + table[recall]
            table[f"{split}_{prefix}_f1"] = (2 * table[precision] * table[recall] / denominator).fillna(0)


def analyze_experiment(experiment_dir: Path, output_dir: Path | None = None) -> dict:
    experiment_dir = Path(experiment_dir).resolve()
    output_dir = Path(output_dir).resolve() if output_dir else experiment_dir / "analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    table = build_seed_performance_table(experiment_dir)
    if table.empty: raise ValueError(f"seed 결과가 없습니다: {experiment_dir}")
    _add_f1(table, "validation"); _add_f1(table, "test")
    table.to_csv(output_dir / "seed_performance.csv", index=False)
    diagnoses = {}
    for run in sorted(experiment_dir.glob("seed_*")):
        results = run / "train/results.csv"
        if results.is_file(): diagnoses[run.name] = diagnose_training_run(pd.read_csv(results))
    numeric = [name for name in table if name != "seed" and pd.api.types.is_numeric_dtype(table[name])]
    summary = {name: {"mean": float(table[name].mean()), "std": float(table[name].std(ddof=1)) if len(table) > 1 else 0.0, "min": float(table[name].min()), "max": float(table[name].max())} for name in numeric}
    report = {"schema_version": 1, "experiment_dir": str(experiment_dir), "seeds": table["seed"].tolist(), "diagnoses": diagnoses, "summary": summary}
    (output_dir / "performance_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Multi-seed segmentation performance", "",
        "주요 판단 지표: person mask mAP50-95, person mask recall, person mask F1. "
        "Pixel accuracy는 배경 비중에 민감하므로 보조 지표로만 사용합니다.", "",
        *_markdown_table(table), "", "## Training diagnostics", "",
    ]
    lines.extend(f"- {seed}: {', '.join(value['warnings']) or 'no automatic warning'}" for seed, value in diagnoses.items())
    (output_dir / "performance_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    save_seed_dashboard(table, output_dir / "seed_dashboard.png")
    save_training_curves(experiment_dir, output_dir / "training_curves.png")
    return report
