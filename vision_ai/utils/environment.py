import importlib.metadata
import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any


class EnvironmentError(RuntimeError):
    pass


def _git_info() -> dict[str, Any]:
    def run(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return "unknown"
    return {"sha": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain"))}


def _nvidia_info() -> dict[str, Any]:
    try:
        text = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            check=True, capture_output=True, text=True,
        ).stdout.strip().splitlines()[0]
        full = subprocess.run(["nvidia-smi"], check=True, capture_output=True, text=True).stdout
        match = re.search(r"CUDA Version:\s*([0-9.]+)", full)
        return {"driver_version": text, "driver_cuda": match.group(1) if match else "unknown"}
    except (OSError, subprocess.CalledProcessError, IndexError):
        return {"driver_version": "unavailable", "driver_cuda": "unavailable"}


def capture_environment(
    dataset_fingerprint: str,
    torch_module=None,
    package_versions: dict[str, str] | None = None,
    git_info: dict[str, Any] | None = None,
    nvidia_info: dict[str, Any] | None = None,
    gpu_index: int = 0,
) -> dict[str, Any]:
    if torch_module is None:
        try:
            import torch as torch_module
        except ImportError:
            torch_module = None
    versions = dict(package_versions or {})
    if package_versions is None:
        for package in ("ultralytics", "albumentations"):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                versions[package] = "unavailable"
    cuda_available = bool(torch_module and torch_module.cuda.is_available())
    gpu = {
        "index": gpu_index if cuda_available else None,
        "name": torch_module.cuda.get_device_name(gpu_index) if cuda_available else "unavailable",
        "compute_capability": ".".join(map(str, torch_module.cuda.get_device_capability(gpu_index))) if cuda_available else "unavailable",
    }
    pytorch = {
        "version": getattr(torch_module, "__version__", "unavailable"),
        "cuda_available": cuda_available,
        "cuda_runtime": getattr(getattr(torch_module, "version", None), "cuda", None) or "unavailable",
        "cudnn_version": torch_module.backends.cudnn.version() if torch_module else None,
        "supported_arches": list(torch_module.cuda.get_arch_list()) if cuda_available else [],
    }
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "python": {"version": platform.python_version(), "executable": sys.executable},
        "gpu": gpu, "nvidia": nvidia_info or _nvidia_info(), "pytorch": pytorch,
        "packages": versions, "dataset": {"fingerprint": dataset_fingerprint},
        "git": git_info or _git_info(),
    }


def validate_training_environment(snapshot: dict[str, Any], require_cuda: bool = True) -> None:
    if require_cuda and not snapshot["pytorch"]["cuda_available"]:
        raise EnvironmentError("no CUDA GPU is available")
    if "RTX 5080" in snapshot["gpu"]["name"]:
        if "sm_120" not in snapshot["pytorch"]["supported_arches"]:
            raise EnvironmentError("training on an RTX 5080 needs a PyTorch build with sm_120 support")
        runtime = snapshot["pytorch"]["cuda_runtime"]
        if runtime == "unavailable" or tuple(map(int, runtime.split(".")[:2])) < (12, 8):
            raise EnvironmentError("training on an RTX 5080 needs PyTorch CUDA runtime 12.8 or newer")


def write_environment(path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
