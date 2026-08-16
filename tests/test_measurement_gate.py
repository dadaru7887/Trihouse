"""실제 호스트 계측 전까지 상태가 UNMEASURED로 남는지 검증한다."""

import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# `tools/` is gitignored in this repository, so the gate lives under `scripts/`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from measurement_gate import (  # noqa: E402
    MINIMUM_SOAK_SECONDS,
    REQUIRED_OUTPUTS,
    REQUIRED_STREAM_COUNT,
    evaluate_measurements,
)


def _stream(camera_id: str) -> dict:
    return {
        "camera_id": camera_id,
        "codec": "h264",
        "resolution": "1280x720",
        "source_fps": 30.0,
        "decoded_fps": 29.6,
        "bitrate_kbps": 2400,
        "dropped_frames": 4,
        "qr_aruco_latency_ms": 38.2,
        "cpu_percent": 41.0,
        "gpu_percent": 22.0,
        "ram_mb": 1820,
        "bytes_written": 540_000_000,
    }


def _measured_directory(tmp_path: Path, **soak_overrides) -> Path:
    for name in REQUIRED_OUTPUTS:
        if name != "camera_soak.json":
            (tmp_path / name).write_text(f"{name} output\n", encoding="utf-8")
    soak = {
        "host": "trihouse-4060",
        "duration_s": MINIMUM_SOAK_SECONDS,
        "streams": [_stream(f"CAM-{index}") for index in range(REQUIRED_STREAM_COUNT)],
    }
    soak.update(soak_overrides)
    (tmp_path / "camera_soak.json").write_text(
        json.dumps(soak), encoding="utf-8"
    )
    return tmp_path


def test_missing_real_host_outputs_are_unmeasured(tmp_path: Path) -> None:
    report = evaluate_measurements(tmp_path)

    assert report.status == "UNMEASURED"
    assert set(report.missing) == {
        "nvidia_smi.txt", "free.txt", "lsblk.txt", "df.txt", "camera_soak.json",
    }


def test_a_complete_real_host_capture_is_measured(tmp_path: Path) -> None:
    report = evaluate_measurements(_measured_directory(tmp_path))

    assert report.status == "MEASURED"
    assert report.missing == ()


def test_an_empty_output_file_does_not_count(tmp_path: Path) -> None:
    directory = _measured_directory(tmp_path)
    (directory / "nvidia_smi.txt").write_text("", encoding="utf-8")

    report = evaluate_measurements(directory)

    assert report.status == "UNMEASURED"
    assert report.missing == ("nvidia_smi.txt",)


def test_a_short_fixture_run_never_flips_the_status(tmp_path: Path) -> None:
    directory = _measured_directory(tmp_path, duration_s=30)

    report = evaluate_measurements(directory)

    assert report.status == "UNMEASURED"
    assert report.missing == ("camera_soak.json",)
    assert "1800" in report.detail


def test_fewer_than_six_streams_is_not_a_soak(tmp_path: Path) -> None:
    directory = _measured_directory(
        tmp_path, streams=[_stream("CAM-1"), _stream("CAM-2")]
    )

    report = evaluate_measurements(directory)

    assert report.status == "UNMEASURED"
    assert "6-stream" in report.detail


def test_every_required_metric_must_be_recorded(tmp_path: Path) -> None:
    incomplete = _stream("CAM-1")
    del incomplete["qr_aruco_latency_ms"]
    directory = _measured_directory(
        tmp_path,
        streams=[incomplete]
        + [_stream(f"CAM-{index}") for index in range(1, REQUIRED_STREAM_COUNT)],
    )

    report = evaluate_measurements(directory)

    assert report.status == "UNMEASURED"
    assert "qr_aruco_latency_ms" in report.detail


def test_a_fixture_host_label_is_rejected(tmp_path: Path) -> None:
    directory = _measured_directory(tmp_path, host="fixture")

    report = evaluate_measurements(directory)

    assert report.status == "UNMEASURED"
    assert "real host" in report.detail


def test_unreadable_soak_artifact_is_reported(tmp_path: Path) -> None:
    directory = _measured_directory(tmp_path)
    (directory / "camera_soak.json").write_text("{not json", encoding="utf-8")

    report = evaluate_measurements(directory)

    assert report.status == "UNMEASURED"
    assert "unreadable" in report.detail


def test_gate_requires_exactly_the_documented_outputs() -> None:
    assert REQUIRED_OUTPUTS == (
        "nvidia_smi.txt", "free.txt", "lsblk.txt", "df.txt", "camera_soak.json",
    )


# --- 계측 스크립트가 짧은 실행으로 상태를 바꾸지 못한다 ------------------------


def _load_soak_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "camera_soak_test",
        Path(__file__).resolve().parents[1] / "scripts" / "camera_soak_test.py",
    )
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves string annotations through sys.modules, so the
    # module has to be registered before it is executed.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_a_soak_needs_exactly_six_streams() -> None:
    module = _load_soak_module()

    with pytest.raises(ValueError, match="exactly 6 streams"):
        module.run_soak(
            camera_ids=["CAM-1"],
            duration_s=1.0,
            sampler=lambda camera_id: None,
        )


def test_a_short_script_run_labels_itself_and_stays_unmeasured(
    tmp_path: Path,
) -> None:
    module = _load_soak_module()
    clock = iter([0.0, 0.0, 10.0, 10.0, 10.0])

    def sampler(camera_id: str):
        return module.StreamSample(
            camera_id=camera_id,
            codec="h264",
            resolution="1280x720",
            source_fps=30.0,
            decoded_fps=29.0,
            bitrate_kbps=2400.0,
            dropped_frames=1,
            qr_aruco_latency_ms=40.0,
            cpu_percent=35.0,
            gpu_percent=20.0,
            ram_mb=1500.0,
            bytes_written=1_000,
        )

    document = module.run_soak(
        camera_ids=[f"CAM-{index}" for index in range(6)],
        duration_s=5.0,
        sampler=sampler,
        clock=lambda: next(clock),
        sleeper=lambda _seconds: None,
        host="trihouse-4060",
    )

    assert "1800" in document["note"]
    assert len(document["streams"]) == 6

    for name in REQUIRED_OUTPUTS:
        if name != "camera_soak.json":
            (tmp_path / name).write_text("output\n", encoding="utf-8")
    (tmp_path / "camera_soak.json").write_text(
        json.dumps(document), encoding="utf-8"
    )

    # 짧은 fixture 실행은 절대 운영 상태를 MEASURED로 바꾸지 않는다.
    assert evaluate_measurements(tmp_path).status == "UNMEASURED"


def test_the_script_refuses_to_fabricate_throughput_numbers() -> None:
    module = _load_soak_module()

    with pytest.raises(RuntimeError, match="never fabricates"):
        module._placeholder_sampler("CAM-PK-01")


def test_the_host_measurement_script_is_executable() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "measure_control_hosts.sh"

    assert script.is_file()
    assert script.stat().st_mode & 0o111
    text = script.read_text(encoding="utf-8")
    for command in ("nvidia-smi", "free -h", "df -h"):
        assert command in text
    assert "lsblk -o NAME,MODEL,TRAN,SIZE,FSTYPE,MOUNTPOINTS" in text
