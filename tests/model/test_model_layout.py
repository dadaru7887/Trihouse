from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_model_tree_is_the_only_vision_source_tree() -> None:
    """모델 코드가 합의한 세 책임 아래에만 있어야 중복 구현을 막을 수 있다."""
    assert (ROOT / "model/perception").is_dir()
    assert (ROOT / "model/worker/person/posture.py").is_file()
    assert not (ROOT / "vision_perception").exists()
    assert not (ROOT / "vision_system").exists()
    assert not (ROOT / "vision_edge").exists()
