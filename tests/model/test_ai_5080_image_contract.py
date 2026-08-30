from pathlib import Path


def test_ai_5080_uses_the_approved_pytorch_cuda_base() -> None:
    dockerfile = Path("docker/ai/Dockerfile.inference").read_text(encoding="utf-8")
    assert "pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime" in dockerfile


def test_ai_5080_build_context_contains_every_inference_package() -> None:
    ignored = Path(".dockerignore").read_text(encoding="utf-8")
    for rule in (
        "!vision_ai/robot/**",
        "!vision_ai/utils/**",
        "!vision_ai/models/perception/detector.py",
        "!vision_ai/models/recovery/policy_architecture.py",
        "!vision_ai/models/recovery/distilled_selector.py",
    ):
        assert rule in ignored


def test_gateway_testclient_uses_httpx2_291() -> None:
    requirements = Path("fms_gateway/requirements-dev.txt").read_text(encoding="utf-8")
    assert "httpx2==2.9.1" in requirements.splitlines()
    assert "httpx==0.28.1" not in requirements.splitlines()


def test_the_robot_image_context_excludes_every_trainer() -> None:
    """학습 코드가 컨텍스트에 있으면 언젠가 이미지로 새어 들어간다."""
    ignored = Path(".dockerignore").read_text(encoding="utf-8")
    for leaked in ("!vision_ai/models/perception/trainer",
                   "!vision_ai/models/recovery/trainer",
                   "!vision_ai/data_loader",
                   "!vision_ai/visualization"):
        assert leaked not in ignored
