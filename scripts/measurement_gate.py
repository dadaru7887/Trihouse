"""실제 호스트 계측이 끝났는지 판정하는 게이트.

4060/OMEN 5080 동시성, 저장 모드, 보존 기간은 실제 장비에서 필요한 명령과
30분 6-스트림 soak를 돌리기 전까지 `UNMEASURED`로 남는다. 이 모듈은 필요한
산출물이 **전부** 있고 내용이 의미 있을 때만 `MEASURED`로 바꾼다. 짧은
fixture 실행은 스크립트를 시험할 수는 있어도 운영 상태를 바꿀 수 없다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


# 실제 호스트에서만 만들 수 있는 산출물.
REQUIRED_OUTPUTS = (
    "nvidia_smi.txt",
    "free.txt",
    "lsblk.txt",
    "df.txt",
    "camera_soak.json",
)

# 설계가 요구하는 최소 soak 길이와 스트림 수.
MINIMUM_SOAK_SECONDS = 1800
REQUIRED_STREAM_COUNT = 6


@dataclass(frozen=True)
class MeasurementReport:
    status: Literal["UNMEASURED", "MEASURED"]
    missing: tuple[str, ...]
    detail: str = ""


def evaluate_measurements(path: Path) -> MeasurementReport:
    """산출물 디렉터리 하나를 보고 계측 완료 여부를 판정한다."""
    directory = Path(path)
    missing = tuple(
        name
        for name in REQUIRED_OUTPUTS
        if not (directory / name).is_file() or (directory / name).stat().st_size == 0
    )
    if missing:
        return MeasurementReport("UNMEASURED", missing)

    soak = directory / "camera_soak.json"
    try:
        document = json.loads(soak.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        return MeasurementReport(
            "UNMEASURED", ("camera_soak.json",), f"soak artifact is unreadable: {error}"
        )

    detail = _soak_shortfall(document)
    if detail:
        # 짧은 fixture 실행은 스크립트 시험일 뿐 계측이 아니다.
        return MeasurementReport("UNMEASURED", ("camera_soak.json",), detail)

    return MeasurementReport("MEASURED", ())


def _soak_shortfall(document: object) -> str:
    if not isinstance(document, dict):
        return "soak artifact must be a JSON object"
    duration = document.get("duration_s")
    if not isinstance(duration, (int, float)) or duration < MINIMUM_SOAK_SECONDS:
        return (
            f"soak ran for {duration!r}s; "
            f"at least {MINIMUM_SOAK_SECONDS}s is required"
        )
    streams = document.get("streams")
    if not isinstance(streams, list) or len(streams) != REQUIRED_STREAM_COUNT:
        return f"a {REQUIRED_STREAM_COUNT}-stream soak is required"
    required_fields = {
        "camera_id", "codec", "resolution", "source_fps", "decoded_fps",
        "bitrate_kbps", "dropped_frames", "qr_aruco_latency_ms",
        "cpu_percent", "gpu_percent", "ram_mb", "bytes_written",
    }
    for stream in streams:
        if not isinstance(stream, dict):
            return "every soak stream must be a JSON object"
        absent = sorted(required_fields - stream.keys())
        if absent:
            return f"soak stream is missing {', '.join(absent)}"
    if document.get("host") in (None, "", "fixture"):
        return "soak artifact must name the real host it ran on"
    return ""


__all__ = [
    "MINIMUM_SOAK_SECONDS",
    "MeasurementReport",
    "REQUIRED_OUTPUTS",
    "REQUIRED_STREAM_COUNT",
    "evaluate_measurements",
]
