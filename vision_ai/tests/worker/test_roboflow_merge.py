"""두 Roboflow export 를 하나의 학습 데이터셋으로 합치는 규칙."""

import json
from pathlib import Path

import pytest

from vision_ai.data_loader.perception.roboflow_merge import (
    MERGED_CLASSES, episode_of, plan_splits, remap_label_text, merge_exports,
)


# ---------------------------------------------- 에피소드 식별


@pytest.mark.parametrize(("filename", "expected"), [
    ("dataset_video_20260822_162137_t0000-00s_jpg.rf.abc123.jpg", "20260822_162137"),
    ("dataset_video_20260822_171506_t0059-00s_jpg.rf.def456.jpg", "20260822_171506"),
    ("frame_0013-00s_jpg.rf.1040bf.jpg", "legacy_frames"),
])
def test_episode_is_read_from_the_filename(filename: str, expected: str) -> None:
    assert episode_of(filename) == expected


# ---------------------------------------------- 클래스 리매핑


def test_fallen_and_standing_both_become_person() -> None:
    """세그멘테이션은 사람이 서 있는지 누웠는지 구분하지 않는다."""
    mapping = {0: 1, 1: 0, 2: 1}          # Fallen->person, Obstacle->obstacle, Standing->person
    text = "0 0.1 0.1 0.2 0.2 0.3 0.1\n2 0.5 0.5 0.6 0.6 0.7 0.5\n"

    out = remap_label_text(text, mapping)

    assert [line.split()[0] for line in out.splitlines()] == ["1", "1"]


def test_coordinates_pass_through_untouched() -> None:
    mapping = {0: 1}
    text = "0 0.1 0.2 0.3 0.4 0.5 0.6\n"

    assert remap_label_text(text, mapping).split()[1:] == text.split()[1:]


def test_a_class_outside_the_mapping_is_refused() -> None:
    """조용히 버리면 인스턴스가 사라진 걸 아무도 모른다."""
    with pytest.raises(ValueError, match="9"):
        remap_label_text("9 0.1 0.1 0.2 0.2 0.3 0.1\n", {0: 1})


def test_blank_lines_are_dropped() -> None:
    assert remap_label_text("\n0 0.1 0.1 0.2 0.2 0.3 0.1\n\n", {0: 1}).count("\n") == 1


# ---------------------------------------------- 에피소드 단위 split


def _stats(**episodes):
    """{episode: (frames, fallen)} 를 plan_splits 입력 형태로."""
    return {name: {"frames": f, "fallen": n} for name, (f, n) in episodes.items()}


def test_an_episode_never_lands_in_two_splits() -> None:
    """프레임 단위로 나누면 test 가 실력이 아니라 암기를 잰다."""
    stats = _stats(**{f"ep{i}": (50, 12) for i in range(8)})

    plan = plan_splits(stats, seed=42)

    assigned = [e for eps in plan.values() for e in eps]
    assert sorted(assigned) == sorted(stats)


def test_every_split_gets_at_least_one_episode() -> None:
    plan = plan_splits(_stats(a=(50, 12), b=(50, 12), c=(50, 12)), seed=1)

    assert all(plan[s] for s in ("train", "valid", "test"))


def test_the_same_input_gives_the_same_plan() -> None:
    stats = _stats(**{f"ep{i}": (50, 12) for i in range(8)})

    assert plan_splits(stats, seed=7) == plan_splits(stats, seed=7)


def test_legacy_frames_are_pinned_to_train() -> None:
    """에피소드를 모르는 프레임은 valid/test 에 넣으면 누수 위험이 있다."""
    stats = _stats(legacy_frames=(77, 0), a=(50, 12), b=(50, 12), c=(50, 12))

    assert "legacy_frames" in plan_splits(stats, seed=3)["train"]


def test_valid_and_test_each_reach_the_minimum_fallen_count() -> None:
    """fallen 이 모자란 평가 split 은 낙상 성능을 잴 수 없다.

    무작위 배정은 이걸 못 맞춘다 -- 실제 데이터에서 valid 가 9개로 한 개 모자랐다.
    """
    stats = _stats(**{
        "big_fallen_a": (167, 49), "big_fallen_b": (121, 42),
        "mid_fallen": (60, 25), "small_fallen_a": (32, 14),
        "small_fallen_b": (15, 12), "small_fallen_c": (58, 12),
        "few_fallen_a": (77, 7), "few_fallen_b": (65, 2),
        "legacy_frames": (77, 0),
    })

    plan = plan_splits(stats, seed=42, min_fallen=10)

    for split in ("valid", "test"):
        total = sum(stats[e]["fallen"] for e in plan[split])
        assert total >= 10, f"{split} fallen={total}"


def test_an_impossible_minimum_is_refused_rather_than_silently_missed() -> None:
    stats = _stats(a=(50, 1), b=(50, 1), c=(50, 1), d=(50, 1))

    with pytest.raises(ValueError, match="fallen"):
        plan_splits(stats, seed=1, min_fallen=10)


# ---------------------------------------------- 병합 결과


def _export(root: Path, name: str, names: list[str], images: dict[str, list[str]]) -> Path:
    base = root / name
    (base).mkdir(parents=True)
    (base / "data.yaml").write_text(
        "names:\n" + "".join(f"- {n}\n" for n in names) + f"nc: {len(names)}\n", encoding="utf-8")
    for split, files in images.items():
        (base / split / "images").mkdir(parents=True)
        (base / split / "labels").mkdir(parents=True)
        for f in files:
            (base / split / "images" / f).write_bytes(b"\xff\xd8fake")
            (base / split / "labels" / f.replace(".jpg", ".txt")).write_text(
                "0 0.1 0.1 0.2 0.2 0.3 0.1\n", encoding="utf-8")
    return base


def test_merge_writes_two_classes_and_a_posture_manifest(tmp_path: Path) -> None:
    fallen = _export(tmp_path, "fallen", ["Fallen", "Obstacle", "Standing"],
                     {"train": [f"dataset_video_20260822_16213{i}_t0_jpg.rf.a{i}.jpg" for i in range(4)]})
    seg = _export(tmp_path, "seg", ["obstacle", "person"],
                  {"train": ["frame_0001-00s_jpg.rf.b1.jpg"]})
    out = tmp_path / "merged"

    report = merge_exports({"fallen": fallen, "segmentation": seg}, out,
                           seed=42, min_fallen=1)

    data = (out / "data.yaml").read_text(encoding="utf-8")
    assert "obstacle" in data and "person" in data
    assert "nc: 2" in data
    manifest = (out / "posture_manifest.csv").read_text(encoding="utf-8")
    assert manifest.splitlines()[0] == "image,posture,environment"
    assert report["images"] == 5


def test_merge_refuses_to_overwrite_an_existing_output(tmp_path: Path) -> None:
    seg = _export(tmp_path, "seg", ["obstacle", "person"], {"train": ["frame_1_jpg.rf.b.jpg"]})
    out = tmp_path / "merged"
    out.mkdir()
    (out / "stale.txt").write_text("x", encoding="utf-8")

    with pytest.raises(FileExistsError):
        merge_exports({"segmentation": seg}, out, seed=1, min_fallen=1)


def test_the_merged_class_order_matches_the_runtime_contract() -> None:
    """realtime.yaml 의 person_class_id: 1 과 어긋나면 사람과 장애물이 뒤집힌다."""
    assert MERGED_CLASSES == ["obstacle", "person"]


def test_each_eval_split_gets_more_than_one_episode_when_possible() -> None:
    """평가 split 이 한 영상뿐이면 그 영상의 특성과 일반화를 구분할 수 없다."""
    stats = _stats(**{
        "a": (167, 49), "b": (121, 42), "c": (60, 25), "d": (32, 14),
        "e": (15, 12), "f": (58, 12), "g": (77, 7), "h": (65, 2),
        "legacy_frames": (77, 0),
    })

    plan = plan_splits(stats, seed=42, min_fallen=10)

    assert len(plan["valid"]) >= 2
    assert len(plan["test"]) >= 2


def test_frame_counts_stay_near_the_target_ratio() -> None:
    stats = _stats(**{
        "a": (167, 49), "b": (121, 42), "c": (60, 25), "d": (32, 14),
        "e": (15, 12), "f": (58, 12), "g": (77, 7), "h": (65, 2),
    })

    plan = plan_splits(stats, seed=42, min_fallen=10)
    frames = {s: sum(stats[e]["frames"] for e in eps) for s, eps in plan.items()}
    total = sum(frames.values())

    # train should hold the clear majority, and neither eval split should
    # swallow more than a third of the data.
    assert frames["train"] / total > 0.45
    assert frames["valid"] / total < 0.35
    assert frames["test"] / total < 0.35
