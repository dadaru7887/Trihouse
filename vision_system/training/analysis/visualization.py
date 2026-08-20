from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def dashboard_metrics(table: pd.DataFrame) -> list[str]:
    preferred = (
        "validation_person_mask_recall", "validation_person_mask_map50_95",
        "validation_person_mask_precision", "validation_person_mask_f1",
        "test_person_mask_recall", "test_person_mask_map50_95",
        "test_person_mask_precision", "test_person_mask_f1",
    )
    fallback = (
        "validation_mask_recall", "validation_mask_map50_95", "validation_mask_precision",
        "validation_mask_f1", "test_mask_recall", "test_mask_map50_95",
    )
    person_metrics = [name for name in preferred if name in table]
    return person_metrics or [name for name in fallback if name in table]


def save_seed_dashboard(table: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    metrics = dashboard_metrics(table)
    fig, axes = plt.subplots(2, 1, figsize=(14, 10), constrained_layout=True)
    if metrics:
        x = np.arange(len(table)); width = 0.8 / len(metrics)
        for index, metric in enumerate(metrics):
            axes[0].bar(x + index * width, table[metric], width, label=metric)
        axes[0].set_xticks(x + width * (len(metrics) - 1) / 2, table["seed"].astype(str))
        axes[0].set_ylim(0, 1); axes[0].set_ylabel("score"); axes[0].set_title("Seed comparison")
        axes[0].legend(fontsize=8, ncol=3)
        matrix = table[metrics].to_numpy(dtype=float)
        image = axes[1].imshow(matrix, vmin=0, vmax=1, cmap="viridis", aspect="auto")
        axes[1].set_yticks(range(len(table)), table["seed"].astype(str)); axes[1].set_ylabel("seed")
        axes[1].set_xticks(range(len(metrics)), metrics, rotation=35, ha="right", fontsize=8)
        fig.colorbar(image, ax=axes[1], label="score")
    else:
        axes[0].text(.5, .5, "No evaluation metrics", ha="center"); axes[1].axis("off")
    fig.savefig(output, dpi=160); plt.close(fig)


def save_training_curves(experiment_dir: Path, output: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(13, 9), constrained_layout=True)
    found = False
    for run in sorted(Path(experiment_dir).glob("seed_*")):
        path = run / "train/results.csv"
        if not path.is_file(): continue
        frame = pd.read_csv(path); frame.columns = [column.strip() for column in frame]
        seed = run.name.split("_")[-1]; found = True
        for metric in ("metrics/mAP50(M)", "metrics/mAP50-95(M)"):
            if metric in frame: axes[0].plot(frame["epoch"], frame[metric], label=f"seed {seed} {metric}")
        for metric in ("train/seg_loss", "val/seg_loss"):
            if metric in frame: axes[1].plot(frame["epoch"], frame[metric], label=f"seed {seed} {metric}")
    for axis, title in zip(axes, ("Mask validation metrics", "Segmentation loss")):
        axis.set_title(title); axis.set_xlabel("epoch"); axis.grid(alpha=.25)
        if found: axis.legend(fontsize=8, ncol=2)
    fig.savefig(output, dpi=160); plt.close(fig)
