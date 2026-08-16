#!/usr/bin/env python3
"""여섯 스트림 soak 계측기.

각 스트림의 코덱·해상도·소스 FPS·디코딩 FPS·비트레이트·드롭·QR/ArUco 지연·
CPU·GPU·RAM·기록 바이트를 최소 1800초 동안 기록한다. 짧은 실행으로도
스크립트 자체는 시험할 수 있지만, 그 산출물은 `tools/measurement_gate.py`가
`UNMEASURED`로 판정한다. 운영 상태는 실제 호스트에서 30분을 채워야만
바뀐다.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence


MINIMUM_SOAK_SECONDS = 1800
REQUIRED_STREAM_COUNT = 6


@dataclass(frozen=True)
class StreamSample:
    camera_id: str
    codec: str
    resolution: str
    source_fps: float
    decoded_fps: float
    bitrate_kbps: float
    dropped_frames: int
    qr_aruco_latency_ms: float
    cpu_percent: float
    gpu_percent: float
    ram_mb: float
    bytes_written: int


def run_soak(
    *,
    camera_ids: Sequence[str],
    duration_s: float,
    sampler: Callable[[str], StreamSample],
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    interval_s: float = 30.0,
    host: str | None = None,
) -> dict:
    """스트림별 표본을 모아 하나의 soak 산출물로 만든다."""
    if len(camera_ids) != REQUIRED_STREAM_COUNT:
        raise ValueError(
            f"a soak needs exactly {REQUIRED_STREAM_COUNT} streams, "
            f"got {len(camera_ids)}"
        )
    started = clock()
    accumulated: dict[str, list[StreamSample]] = {name: [] for name in camera_ids}
    while clock() - started < duration_s:
        for camera_id in camera_ids:
            accumulated[camera_id].append(sampler(camera_id))
        sleeper(min(interval_s, max(0.0, duration_s - (clock() - started))))

    elapsed = clock() - started
    document = {
        "host": host or socket.gethostname(),
        "duration_s": elapsed,
        "sample_interval_s": interval_s,
        "streams": [
            _summarise(camera_id, samples)
            for camera_id, samples in accumulated.items()
        ],
    }
    if elapsed < MINIMUM_SOAK_SECONDS:
        # 짧은 실행은 스크립트 시험일 뿐이라는 사실을 산출물에 남긴다.
        document["note"] = (
            f"ran for {elapsed:.1f}s; {MINIMUM_SOAK_SECONDS}s is required before "
            "throughput and retention can leave UNMEASURED"
        )
    return document


def _summarise(camera_id: str, samples: list[StreamSample]) -> dict:
    if not samples:
        raise ValueError(f"no samples were collected for {camera_id}")
    numeric = (
        "source_fps", "decoded_fps", "bitrate_kbps", "qr_aruco_latency_ms",
        "cpu_percent", "gpu_percent", "ram_mb",
    )
    summary = {
        "camera_id": camera_id,
        "codec": samples[-1].codec,
        "resolution": samples[-1].resolution,
        "samples": len(samples),
        "dropped_frames": sum(sample.dropped_frames for sample in samples),
        "bytes_written": max(sample.bytes_written for sample in samples),
    }
    for field in numeric:
        values = [getattr(sample, field) for sample in samples]
        summary[field] = sum(values) / len(values)
        summary[f"{field}_max"] = max(values)
    return summary


def _placeholder_sampler(camera_id: str) -> StreamSample:
    """실제 계측기를 붙이기 전까지 쓰는 자리표시자."""
    raise RuntimeError(
        "A real MediaMTX/decoder sampler must be injected before this script can "
        "produce a measurement. P0 never fabricates throughput numbers."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="camera_soak.json path")
    parser.add_argument(
        "--duration-s", type=float, default=float(MINIMUM_SOAK_SECONDS)
    )
    parser.add_argument("--camera-id", action="append", default=[])
    args = parser.parse_args(argv)

    camera_ids = args.camera_id or [
        "CAM-PK-01", "CAM-PK-02", "CAM-OMX-01-WRIST",
        "CAM-OMX-02-WRIST", "CAM-FIXED-01", "CAM-FIXED-02",
    ]
    try:
        document = run_soak(
            camera_ids=camera_ids,
            duration_s=args.duration_s,
            sampler=_placeholder_sampler,
        )
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 3

    args.output.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return 0


__all__ = [
    "MINIMUM_SOAK_SECONDS",
    "REQUIRED_STREAM_COUNT",
    "StreamSample",
    "asdict",
    "run_soak",
]


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
