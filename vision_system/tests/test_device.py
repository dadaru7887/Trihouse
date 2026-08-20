import pytest

from vision_system.inference_common.device import DeviceError, resolve_device


class FakeCuda:
    def __init__(self, available: bool, count: int = 0) -> None:
        self.available = available
        self.count = count

    def is_available(self) -> bool:
        return self.available

    def device_count(self) -> int:
        return self.count


class FakeTorch:
    def __init__(self, available: bool, count: int = 0) -> None:
        self.cuda = FakeCuda(available, count)


def test_auto_uses_first_gpu_when_cuda_is_available() -> None:
    selection = resolve_device("auto", FakeTorch(True, 2))
    assert selection.resolved == "0"
    assert selection.requires_cuda is True
    assert selection.reason == "auto_cuda_available"


def test_auto_falls_back_to_cpu_without_cuda() -> None:
    selection = resolve_device("auto", FakeTorch(False))
    assert selection.resolved == "cpu"
    assert selection.requires_cuda is False
    assert selection.reason == "auto_cuda_unavailable"


def test_cpu_is_always_preserved() -> None:
    selection = resolve_device("cpu", FakeTorch(True, 2))
    assert selection.resolved == "cpu"
    assert selection.requires_cuda is False


@pytest.mark.parametrize(("requested", "resolved"), [("gpu", "0"), ("cuda", "0"), ("0", "0"), ("1", "1"), ("cuda:1", "1")])
def test_gpu_policy_requires_and_resolves_requested_gpu(requested: str, resolved: str) -> None:
    selection = resolve_device(requested, FakeTorch(True, 2))
    assert selection.resolved == resolved
    assert selection.requires_cuda is True


@pytest.mark.parametrize("requested", ["gpu", "cuda", "0", "cuda:0"])
def test_gpu_policy_never_falls_back_to_cpu(requested: str) -> None:
    with pytest.raises(DeviceError, match="CUDA GPU가 필요"):
        resolve_device(requested, FakeTorch(False))


def test_out_of_range_gpu_is_rejected() -> None:
    with pytest.raises(DeviceError, match="GPU index 2"):
        resolve_device("cuda:2", FakeTorch(True, 2))


def test_invalid_device_is_rejected() -> None:
    with pytest.raises(DeviceError, match="지원하지 않는 device"):
        resolve_device("mps", FakeTorch(False))
