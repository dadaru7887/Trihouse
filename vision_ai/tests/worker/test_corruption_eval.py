"""평가셋을 고정하고 손상만 바꾸는 하네스 (ImageNet-C 방식)."""

from pathlib import Path

import pytest

pytest.importorskip("albumentations")
pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from vision_ai.models.perception.trainer.corruption_eval import build_corrupted_split


def _dataset(root: Path, n_images: int = 3) -> Path:
    (root / "valid" / "images").mkdir(parents=True)
    (root / "valid" / "labels").mkdir(parents=True)
    import cv2

    for i in range(n_images):
        image = np.random.default_rng(i).integers(0, 255, (64, 80, 3), dtype=np.uint8)
        cv2.imwrite(str(root / "valid" / "images" / f"f{i}.jpg"), image)
        (root / "valid" / "labels" / f"f{i}.txt").write_text(
            "1 0.1 0.1 0.2 0.2 0.3 0.1\n", encoding="utf-8")
    yaml_path = root / "data.yaml"
    yaml_path.write_text(
        "names:\n- obstacle\n- person\nnc: 2\n"
        "train: train/images\nval: valid/images\ntest: test/images\n", encoding="utf-8")
    return yaml_path


def test_it_writes_a_dataset_yaml_pointing_at_the_corrupted_images(tmp_path: Path) -> None:
    data = _dataset(tmp_path / "src")

    out = build_corrupted_split(data, "valid", "S4", tmp_path / "out", seed=42)

    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "val: valid/images" in text
    assert len(list((tmp_path / "out" / "valid" / "images").iterdir())) == 3


def test_labels_are_copied_unchanged(tmp_path: Path) -> None:
    """광학 손상은 그림만 바꾼다. 라벨이 바뀌면 평가가 무의미해진다."""
    data = _dataset(tmp_path / "src")

    build_corrupted_split(data, "valid", "S2", tmp_path / "out", seed=1)

    for label in (tmp_path / "out" / "valid" / "labels").iterdir():
        assert label.read_text(encoding="utf-8") == "1 0.1 0.1 0.2 0.2 0.3 0.1\n"


def test_the_images_actually_change(tmp_path: Path) -> None:
    import cv2

    data = _dataset(tmp_path / "src")
    build_corrupted_split(data, "valid", "S4", tmp_path / "out", seed=42)

    before = cv2.imread(str(tmp_path / "src" / "valid" / "images" / "f0.jpg"))
    after = cv2.imread(str(tmp_path / "out" / "valid" / "images" / "f0.jpg"))

    assert not np.array_equal(before, after)


def test_the_same_seed_produces_the_same_corruption(tmp_path: Path) -> None:
    import cv2

    data = _dataset(tmp_path / "src")
    build_corrupted_split(data, "valid", "S4", tmp_path / "a", seed=7)
    build_corrupted_split(data, "valid", "S4", tmp_path / "b", seed=7)

    a = cv2.imread(str(tmp_path / "a" / "valid" / "images" / "f0.jpg"))
    b = cv2.imread(str(tmp_path / "b" / "valid" / "images" / "f0.jpg"))

    assert np.array_equal(a, b)


def test_the_clean_baseline_copies_images_untouched(tmp_path: Path) -> None:
    """clean 은 손상 없이 같은 경로 규약으로 만들어 비교 기준이 된다."""
    import cv2

    data = _dataset(tmp_path / "src")
    build_corrupted_split(data, "valid", "clean", tmp_path / "out", seed=42)

    before = cv2.imread(str(tmp_path / "src" / "valid" / "images" / "f0.jpg"))
    after = cv2.imread(str(tmp_path / "out" / "valid" / "images" / "f0.jpg"))

    assert np.array_equal(before, after)


def test_an_unknown_scenario_is_refused(tmp_path: Path) -> None:
    data = _dataset(tmp_path / "src")

    with pytest.raises(ValueError, match="S9"):
        build_corrupted_split(data, "valid", "S9", tmp_path / "out", seed=1)
