"""Resolve a --device request into the device training will actually run on.

Preference order is CUDA, then Apple's MPS, then CPU: a discrete NVIDIA GPU
beats the integrated one, which beats no GPU at all. Only `auto` walks that
order; naming a device means that device or an error, never a quiet
substitution, because a run that silently trains somewhere else reports
numbers nobody asked for.

    resolve_device("auto")     -> the best available
    resolve_device("mps")      -> Apple GPU, or DeviceError
    resolve_device("cuda:1")   -> that GPU, or DeviceError

`requires_cuda` tells the caller whether to run the CUDA-only environment
checks; MPS and CPU both skip them.
"""

from dataclasses import asdict, dataclass
from typing import Any


class DeviceError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeviceSelection:
    requested: str
    resolved: str
    requires_cuda: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mps_available(torch_module) -> bool:
    """Is an Apple GPU usable? Torch builds before 1.12 have no mps backend."""
    backends = getattr(torch_module, "backends", None)
    mps = getattr(backends, "mps", None)
    return bool(mps and mps.is_available())


def resolve_device(requested: str, torch_module=None) -> DeviceSelection:
    """Turn a requested device string into the one to hand the trainer."""
    if torch_module is None:
        try:
            import torch as torch_module
        except ImportError:
            torch_module = None
    value = str(requested).strip().lower()
    cuda = getattr(torch_module, "cuda", None)
    available = bool(cuda and cuda.is_available())
    count = int(cuda.device_count()) if available else 0

    if value == "auto":
        if available and count > 0:
            return DeviceSelection(requested=value, resolved="0", requires_cuda=True,
                                   reason="auto_cuda_available")
        if _mps_available(torch_module):
            return DeviceSelection(requested=value, resolved="mps", requires_cuda=False,
                                   reason="auto_mps_available")
        return DeviceSelection(requested=value, resolved="cpu", requires_cuda=False,
                               reason="auto_cpu_fallback")
    if value == "cpu":
        return DeviceSelection(requested=value, resolved="cpu", requires_cuda=False,
                               reason="explicit_cpu")
    if value == "mps":
        if not _mps_available(torch_module):
            raise DeviceError(f"device={requested} 실행에는 Apple GPU(MPS)가 필요합니다")
        return DeviceSelection(requested=value, resolved="mps", requires_cuda=False,
                               reason="explicit_mps")
    if value in {"gpu", "cuda"}:
        index = 0
    elif value.isdigit():
        index = int(value)
    elif value.startswith("cuda:") and value[5:].isdigit():
        index = int(value[5:])
    else:
        raise DeviceError(f"지원하지 않는 device 값입니다: {requested}")
    if not available:
        raise DeviceError(f"device={requested} 실행에는 CUDA GPU가 필요합니다")
    if index >= count:
        raise DeviceError(f"GPU index {index}를 사용할 수 없습니다. 감지된 GPU 수: {count}")
    return DeviceSelection(requested=value, resolved=str(index), requires_cuda=True,
                           reason="explicit_cuda")
