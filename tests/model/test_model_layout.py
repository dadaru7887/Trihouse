from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_vision_ai_is_the_only_vision_source_tree() -> None:
    """vision 코드가 한 트리 아래에만 있어야 중복 구현을 막을 수 있다."""
    assert (ROOT / "vision_ai").is_dir()
    for gone in ("model", "vision_perception", "vision_system", "vision_edge"):
        assert not (ROOT / gone).exists(), f"{gone} 가 아직 남아 있습니다"


def test_the_two_models_and_the_robot_process_each_have_a_home() -> None:
    """모델 2개와 로봇 프로세스가 각자 자리를 갖는다."""
    assert (ROOT / "vision_ai/models/perception/detector.py").is_file()
    assert (ROOT / "vision_ai/models/recovery/policy_architecture.py").is_file()
    assert (ROOT / "vision_ai/robot/main.py").is_file()


def test_roles_are_split_the_way_the_readme_says() -> None:
    for role in ("data_loader", "models", "utils", "visualization", "robot"):
        assert (ROOT / "vision_ai" / role).is_dir(), role
