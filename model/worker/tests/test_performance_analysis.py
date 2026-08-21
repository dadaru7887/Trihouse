import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from model.perception.segmentation.evaluation.metrics import BinaryCounts, instance_metrics, mask_metrics
from model.perception.segmentation.training.analysis.performance import build_seed_performance_table, diagnose_training_run
from model.perception.segmentation.training.analysis.report import analyze_experiment
from model.perception.segmentation.training.analysis.visualization import dashboard_metrics


def test_instance_metrics_compute_precision_recall_f1() -> None:
    metrics = instance_metrics(BinaryCounts(tp=8, fp=2, fn=4))
    assert metrics["tp"] == 8 and metrics["fp"] == 2 and metrics["fn"] == 4
    assert metrics["precision"] == pytest.approx(0.8)
    assert metrics["recall"] == pytest.approx(2 / 3)
    assert metrics["f1"] == pytest.approx(8 / 11)


def test_mask_metrics_compute_iou_dice_and_pixel_accuracy() -> None:
    target = np.array([[1, 1], [0, 0]], dtype=bool)
    prediction = np.array([[1, 0], [1, 0]], dtype=bool)
    metrics = mask_metrics(prediction, target)
    assert metrics["mask_iou"] == 1 / 3
    assert metrics["dice_f1"] == 0.5
    assert metrics["pixel_accuracy"] == 0.5


def make_seed(root: Path, seed: int, val: dict, test: dict) -> None:
    evaluation = root / f"seed_{seed}" / "evaluation"
    train = root / f"seed_{seed}" / "train"
    evaluation.mkdir(parents=True)
    train.mkdir()
    (evaluation / "validation_metrics.json").write_text(json.dumps(val))
    (evaluation / "test_metrics.json").write_text(json.dumps(test))
    pd.DataFrame({"epoch": [1, 2], "metrics/mAP50(M)": [0.2, 0.4], "train/seg_loss": [2.0, 1.0]}).to_csv(train / "results.csv", index=False)


def test_seed_table_joins_validation_test_and_training_curves(tmp_path: Path) -> None:
    make_seed(tmp_path, 17, {"mask_recall": 0.7, "mask_map50_95": 0.4}, {"mask_recall": 0.6})
    make_seed(tmp_path, 42, {"mask_recall": 0.8, "mask_map50_95": 0.5}, {"mask_recall": 0.7})
    table = build_seed_performance_table(tmp_path)
    assert table["seed"].tolist() == [17, 42]
    assert table.loc[0, "validation_mask_recall"] == 0.7
    assert table.loc[1, "test_mask_recall"] == 0.7
    assert table.loc[0, "final_train_seg_loss"] == 1.0


def test_diagnosis_flags_plateau_and_overfitting() -> None:
    frame = pd.DataFrame({
        "epoch": range(1, 9),
        "metrics/mAP50(M)": [0.1, 0.2, 0.3, 0.31, 0.311, 0.31, 0.31, 0.31],
        "train/seg_loss": [2, 1.5, 1.0, .8, .6, .5, .4, .3],
        "val/seg_loss": [2, 1.6, 1.2, 1.0, 1.1, 1.2, 1.3, 1.4],
    })
    diagnosis = diagnose_training_run(frame, plateau_epochs=4)
    assert "metric_plateau" in diagnosis["warnings"]
    assert "validation_loss_rising" in diagnosis["warnings"]


def test_analysis_writes_tables_reports_and_visualizations(tmp_path: Path) -> None:
    make_seed(tmp_path, 17, {"person_mask_precision": .8, "person_mask_recall": .6, "person_mask_map50_95": .4}, {"person_mask_precision": .7, "person_mask_recall": .5})
    report = analyze_experiment(tmp_path)
    assert report["seeds"] == [17]
    for name in ("seed_performance.csv", "performance_report.json", "performance_report.md", "seed_dashboard.png", "training_curves.png"):
        assert (tmp_path / "analysis" / name).is_file()


def test_dashboard_prefers_person_metrics_over_macro_metrics() -> None:
    table = pd.DataFrame({
        "seed": [17], "validation_mask_recall": [.9],
        "validation_person_mask_recall": [.5], "validation_person_mask_map50_95": [.4],
    })
    assert dashboard_metrics(table)[:2] == [
        "validation_person_mask_recall", "validation_person_mask_map50_95",
    ]
