from pathlib import Path


def test_physical_compose_uses_inference_entrypoint_only() -> None:
    source = Path("compose.ai_5080.yaml").read_text(encoding="utf-8")
    assert "vision_ai.robot.recovery" in source
    assert "vision_ai.models.recovery.trainer" not in source
    assert "MYSQL_" not in source


def test_inference_dockerfile_never_copies_training_package() -> None:
    source = Path("docker/ai/Dockerfile.inference").read_text(encoding="utf-8")
    assert "vlm_rl/training" not in source
    assert "vision_ai.robot.recovery.runtime" in source


def test_offline_training_requires_explicit_profile() -> None:
    source = Path("compose.ai_training.yaml").read_text(encoding="utf-8")
    assert "profiles: [training]" in source
    assert "vision_ai.models.recovery.trainer.offline_train" in Path("docker/ai/Dockerfile.training").read_text(encoding="utf-8")
