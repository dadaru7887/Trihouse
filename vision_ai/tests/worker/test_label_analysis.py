from pathlib import Path

import cv2
import numpy as np
import yaml

from vision_ai.data_loader.perception.label_analysis import analyze_labels


def test_label_analysis_reports_small_persons_and_split_counts(tmp_path: Path) -> None:
    for split in ("train", "valid", "test"):
        images = tmp_path / split / "images"
        labels = tmp_path / split / "labels"
        images.mkdir(parents=True)
        labels.mkdir()
        cv2.imwrite(str(images / "a.jpg"), np.zeros((100, 100, 3), dtype=np.uint8))
        (labels / "a.txt").write_text("1 0.1 0.1 0.15 0.1 0.15 0.15 0.1 0.15\n")
    data = tmp_path / "data.yaml"
    data.write_text(yaml.safe_dump({"train": "train/images", "val": "valid/images", "test": "test/images", "names": ["obstacle", "person"], "nc": 2}))
    report = analyze_labels(data, tmp_path / "analysis")
    assert report["splits"]["train"]["person_instances"] == 1
    assert report["splits"]["train"]["small_person_instances"] == 1
    assert (tmp_path / "analysis/label_analysis.json").is_file()
    assert (tmp_path / "analysis/label_instances.csv").is_file()
