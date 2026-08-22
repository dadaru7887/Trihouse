from pathlib import Path


def test_ai_5080_uses_the_approved_pytorch_cuda_base() -> None:
    dockerfile = Path("docker/ai/Dockerfile.inference").read_text(encoding="utf-8")
    assert "pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime" in dockerfile


def test_ai_5080_build_context_contains_every_inference_package() -> None:
    ignored = Path(".dockerignore").read_text(encoding="utf-8")
    for rule in (
        "!model/worker/**",
        "!model/perception/segmentation/runtime/**",
        "!model/vlm_rl/inference/**",
        "!model/vlm_rl/recovery_memory/**",
        "!model/vlm_rl/safety/**",
    ):
        assert rule in ignored


def test_gateway_testclient_uses_httpx2_291() -> None:
    requirements = Path("fms_gateway/requirements-dev.txt").read_text(encoding="utf-8")
    assert "httpx2==2.9.1" in requirements.splitlines()
    assert "httpx==0.28.1" not in requirements.splitlines()
