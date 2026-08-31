"""Device resolution: CUDA first, then Apple's MPS, then CPU.

    pytest vision_ai/tests/worker/test_device.py

A CUDA request must never silently land on something slower -- the run would
report a finished training that took a different path than asked for.
"""

import pytest

from vision_ai.utils.device import DeviceError, resolve_device


class FakeCuda:
    def __init__(self, available: bool, count: int = 0) -> None:
        self.available = available
        self.count = count

    def is_available(self) -> bool:
        return self.available

    def device_count(self) -> int:
        return self.count


class FakeMps:
    """Stands in for torch.backends.mps."""

    def __init__(self, available: bool) -> None:
        self.available = available

    def is_available(self) -> bool:
        return self.available


class FakeBackends:
    def __init__(self, mps: bool) -> None:
        self.mps = FakeMps(mps)


class FakeTorch:
    def __init__(self, available: bool, count: int = 0, mps: bool = False) -> None:
        self.cuda = FakeCuda(available, count)
        self.backends = FakeBackends(mps)


# ----------------------------------------------------------------- auto --

def test_auto_uses_first_gpu_when_cuda_is_available() -> None:
    selection = resolve_device("auto", FakeTorch(True, 2))
    assert selection.resolved == "0"
    assert selection.requires_cuda is True
    assert selection.reason == "auto_cuda_available"


def test_auto_prefers_cuda_over_mps_when_both_are_present() -> None:
    """A discrete NVIDIA GPU beats an integrated one, so CUDA stays first."""
    selection = resolve_device("auto", FakeTorch(True, 1, mps=True))
    assert selection.resolved == "0"
    assert selection.requires_cuda is True


def test_auto_uses_mps_when_cuda_is_missing() -> None:
    """On Apple Silicon this is the only GPU there is; CPU would waste it."""
    selection = resolve_device("auto", FakeTorch(False, mps=True))
    assert selection.resolved == "mps"
    assert selection.requires_cuda is False
    assert selection.reason == "auto_mps_available"


def test_auto_falls_back_to_cpu_without_any_gpu() -> None:
    selection = resolve_device("auto", FakeTorch(False, mps=False))
    assert selection.resolved == "cpu"
    assert selection.requires_cuda is False
    assert selection.reason == "auto_cpu_fallback"


def test_auto_tolerates_a_torch_without_the_mps_backend() -> None:
    """Older torch builds have no backends.mps; that must not crash resolution."""

    class OldTorch:
        def __init__(self) -> None:
            self.cuda = FakeCuda(False)

    assert resolve_device("auto", OldTorch()).resolved == "cpu"


# ------------------------------------------------------------- explicit --

def test_cpu_is_always_preserved() -> None:
    selection = resolve_device("cpu", FakeTorch(True, 2, mps=True))
    assert selection.resolved == "cpu"
    assert selection.requires_cuda is False


def test_mps_is_resolved_when_available() -> None:
    selection = resolve_device("mps", FakeTorch(False, mps=True))
    assert selection.resolved == "mps"
    assert selection.requires_cuda is False
    assert selection.reason == "explicit_mps"


def test_mps_is_refused_when_the_machine_has_none() -> None:
    """Asking for a GPU that is not there must fail, not quietly use the CPU."""
    with pytest.raises(DeviceError, match="needs an Apple GPU"):
        resolve_device("mps", FakeTorch(False, mps=False))


@pytest.mark.parametrize(("requested", "resolved"),
                         [("gpu", "0"), ("cuda", "0"), ("0", "0"), ("1", "1"), ("cuda:1", "1")])
def test_gpu_policy_requires_and_resolves_requested_gpu(requested: str, resolved: str) -> None:
    selection = resolve_device(requested, FakeTorch(True, 2))
    assert selection.resolved == resolved
    assert selection.requires_cuda is True


@pytest.mark.parametrize("requested", ["gpu", "cuda", "0", "cuda:0"])
def test_a_cuda_request_never_falls_back(requested: str) -> None:
    """Not even to MPS: the run asked for CUDA and must say so if it cannot."""
    with pytest.raises(DeviceError, match="needs a CUDA GPU"):
        resolve_device(requested, FakeTorch(False, mps=True))


def test_out_of_range_gpu_is_rejected() -> None:
    with pytest.raises(DeviceError, match="GPU index 2"):
        resolve_device("cuda:2", FakeTorch(True, 2))


def test_invalid_device_is_rejected() -> None:
    with pytest.raises(DeviceError, match="unsupported device"):
        resolve_device("tpu", FakeTorch(False))
