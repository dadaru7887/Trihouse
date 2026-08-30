"""낙상 분류기 학습: train 으로 맞추고, valid 로 고르고, test 는 마지막에 한 번."""

import json
import math
from pathlib import Path

import pytest

pytest.importorskip("sklearn")
pytest.importorskip("joblib")


def _row(fallen: bool, split: str, jitter: float = 0.0) -> dict:
    """분리 가능한 두 덩어리. aspect_ratio 가 신호를 다 갖고 있다."""
    if fallen:
        features = [2.6 + jitter, 8.0 + jitter, 0.78, 0.04, 0.0]
    else:
        features = [0.35 + jitter, 88.0 + jitter, 0.34, 0.0, 0.0]
    return {"features": features, "fallen": fallen, "split": split}


def dataset(tmp_path: Path, name: str = "features.jsonl") -> Path:
    rows = []
    for split, count in (("train", 24), ("valid", 12), ("test", 12)):
        for index in range(count):
            rows.append(_row(index % 2 == 0, split, jitter=index * 0.01))
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def test_training_writes_a_bundle_the_runtime_can_load(tmp_path) -> None:
    import hashlib

    from vision_ai.models.perception.fall_classifier import FallenClassifier
    from vision_ai.models.perception.trainer.fall_trainer import train_classifier

    result = train_classifier(dataset(tmp_path), tmp_path / "run", seed=42)

    bundle = Path(result["bundle"])
    assert bundle.is_file()
    loaded = FallenClassifier(bundle, hashlib.sha256(bundle.read_bytes()).hexdigest())
    loaded.load()
    assert loaded.threshold == pytest.approx(result["threshold"])
    assert loaded.is_fallen([2.6, 8.0, 0.78, 0.04, 0.0])
    assert not loaded.is_fallen([0.35, 88.0, 0.34, 0.0, 0.0])


def test_the_test_split_never_touches_fitting_or_threshold_choice(tmp_path) -> None:
    """test 를 오염시키면 최종 수치가 성능이 아니라 자기 자신을 재는 게 된다."""
    from vision_ai.models.perception.trainer.fall_trainer import train_classifier

    path = dataset(tmp_path)
    clean = train_classifier(path, tmp_path / "clean", seed=42)

    # test split 라벨을 전부 뒤집는다. 학습·임계값 선택이 test 를 보지 않는다면
    # 모델도 임계값도 그대로여야 한다.
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        if row["split"] == "test":
            row["fallen"] = not row["fallen"]
    poisoned_path = tmp_path / "poisoned.jsonl"
    poisoned_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    poisoned = train_classifier(poisoned_path, tmp_path / "poisoned", seed=42)

    assert poisoned["threshold"] == clean["threshold"]
    assert poisoned["coefficients"] == clean["coefficients"]
    # 반대로 test 지표는 달라져야 한다 -- 안 달라지면 test 를 안 재고 있다는 뜻이다.
    assert poisoned["test"]["recall"] != clean["test"]["recall"]


def test_the_same_seed_reproduces_the_same_model(tmp_path) -> None:
    from vision_ai.models.perception.trainer.fall_trainer import train_classifier

    path = dataset(tmp_path)
    first = train_classifier(path, tmp_path / "a", seed=7)
    second = train_classifier(path, tmp_path / "b", seed=7)

    assert first["coefficients"] == second["coefficients"]
    assert first["threshold"] == second["threshold"]


def test_metrics_are_written_per_split(tmp_path) -> None:
    from vision_ai.models.perception.trainer.fall_trainer import train_classifier

    result = train_classifier(dataset(tmp_path), tmp_path / "run", seed=42)
    written = json.loads((tmp_path / "run" / "metrics.json").read_text(encoding="utf-8"))

    assert set(written) >= {"validation", "test", "threshold", "dataset"}
    for split in ("validation", "test"):
        assert {"precision", "recall", "support"} <= set(written[split])
    assert result["dataset"]["counts"]["train"] == 24


def test_a_recall_floor_is_honoured_when_choosing_the_threshold(tmp_path) -> None:
    """안전 경보라 recall 우선이다: 바닥을 만족하는 것 중 precision 이 가장 높은 것."""
    from vision_ai.models.perception.trainer.fall_trainer import train_classifier

    result = train_classifier(dataset(tmp_path), tmp_path / "run", seed=42, min_recall=0.9)

    assert result["validation"]["recall"] >= 0.9
    assert result["recall_floor_met"] is True


def test_a_missing_split_is_refused(tmp_path) -> None:
    from vision_ai.models.perception.trainer.fall_trainer import DatasetError, train_classifier

    rows = [_row(i % 2 == 0, "train") for i in range(10)]
    path = tmp_path / "only_train.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    with pytest.raises(DatasetError, match="valid"):
        train_classifier(path, tmp_path / "run", seed=42)


def test_a_split_with_no_fallen_examples_is_refused(tmp_path) -> None:
    from vision_ai.models.perception.trainer.fall_trainer import DatasetError, train_classifier

    rows = ([_row(i % 2 == 0, "train") for i in range(20)]
            + [_row(False, "valid") for _ in range(8)]
            + [_row(i % 2 == 0, "test") for i in range(8)])
    path = tmp_path / "no_positives.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    with pytest.raises(DatasetError, match="fallen"):
        train_classifier(path, tmp_path / "run", seed=42)


def test_a_wrong_length_feature_vector_is_refused(tmp_path) -> None:
    from vision_ai.models.perception.trainer.fall_trainer import DatasetError, train_classifier

    rows = [_row(i % 2 == 0, s) for s in ("train", "valid", "test") for i in range(10)]
    rows[0]["features"] = [1.0, 2.0]
    path = tmp_path / "bad.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    with pytest.raises(DatasetError, match="five|다섯"):
        train_classifier(path, tmp_path / "run", seed=42)


def test_the_cli_takes_every_path_as_an_argument() -> None:
    """데이터셋 경로가 코드에 박혀 있으면 안 된다."""
    from vision_ai.models.perception.trainer.fall_trainer import build_parser

    args = build_parser().parse_args([
        "--dataset", "/some/where/features.jsonl", "--out", "/runs/fallen", "--seed", "7",
    ])

    assert str(args.dataset) == "/some/where/features.jsonl"
    assert str(args.out) == "/runs/fallen"
    assert args.seed == 7
