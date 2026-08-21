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


def resolve_device(requested: str, torch_module=None) -> DeviceSelection:
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
            return DeviceSelection(requested=value, resolved="0", requires_cuda=True, reason="auto_cuda_available")
        return DeviceSelection(requested=value, resolved="cpu", requires_cuda=False, reason="auto_cuda_unavailable")
    if value == "cpu":
        return DeviceSelection(requested=value, resolved="cpu", requires_cuda=False, reason="explicit_cpu")
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
    return DeviceSelection(requested=value, resolved=str(index), requires_cuda=True, reason="explicit_cuda")
