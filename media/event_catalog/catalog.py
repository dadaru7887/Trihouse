"""완료된 fixture 이벤트 클립만 `artifacts`에 등록하는 카탈로그.

P0는 여섯 스트림 상시 녹화를 켜지 않는다. 사건이 만들어 낸 클립이 **끝난
뒤에** 그 파일을 해시하고 URI·시간 구간·카메라·Job·Step·사건 관계를 한 행
으로 넣는다. 진행 중인 클립은 등록하지 않는다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


CONTINUOUS_RECORDING_ENABLED = False
ARTIFACT_TYPE = "event_clip"


class EventClipError(ValueError):
    """클립이 등록 조건을 만족하지 못했다."""


@dataclass(frozen=True)
class EventClip:
    """녹화가 끝난 fixture 클립 하나."""

    clip_path: Path
    storage_uri: str
    camera_id: str
    started_at_ms: int
    ended_at_ms: int
    mime_type: str = "video/mp4"
    job_id: int | None = None
    job_step_id: int | None = None
    incident_id: int | None = None
    completed: bool = True

    def __post_init__(self) -> None:
        if not self.storage_uri.strip():
            raise EventClipError("storage_uri is required")
        if not self.camera_id.strip():
            raise EventClipError("camera_id is required")
        if self.started_at_ms <= 0 or self.ended_at_ms <= 0:
            raise EventClipError("clip timestamps must be positive")
        if self.ended_at_ms <= self.started_at_ms:
            raise EventClipError("a clip must end after it starts")

    @property
    def duration_ms(self) -> int:
        return self.ended_at_ms - self.started_at_ms


@dataclass(frozen=True)
class CatalogedArtifact:
    storage_uri: str
    sha256: str
    byte_size: int
    camera_id: str
    started_at_ms: int
    ended_at_ms: int
    job_id: int | None
    job_step_id: int | None
    incident_id: int | None

    def as_artifact_row(self) -> dict[str, Any]:
        """`artifacts` 한 행으로 바꾼다."""
        return {
            "artifact_type": ARTIFACT_TYPE,
            "storage_uri": self.storage_uri,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "device_id": self.camera_id,
            "job_id": self.job_id,
            "job_step_id": self.job_step_id,
            "event_id": self.incident_id,
            "metadata": {
                "camera_id": self.camera_id,
                "started_at_ms": self.started_at_ms,
                "ended_at_ms": self.ended_at_ms,
                "duration_ms": self.ended_at_ms - self.started_at_ms,
                "capture_mode": "event_fixture",
            },
        }


class ArtifactSink(Protocol):
    def insert_artifact(self, row: dict[str, Any]) -> int: ...

    def artifact_exists(self, *, sha256: str, storage_uri: str) -> bool: ...


class EventClipCatalog:
    """끝난 클립을 해시하고 정확히 한 번 등록한다."""

    def __init__(self, sink: ArtifactSink) -> None:
        self._sink = sink

    def catalog(self, clip: EventClip) -> CatalogedArtifact | None:
        if not clip.completed:
            # 진행 중인 클립은 해시가 확정되지 않는다.
            raise EventClipError("only a completed clip can be cataloged")
        if not clip.clip_path.is_file():
            raise EventClipError(f"clip file is missing: {clip.clip_path}")

        digest = sha256_file(clip.clip_path)
        if self._sink.artifact_exists(sha256=digest, storage_uri=clip.storage_uri):
            # 같은 내용을 같은 URI로 두 번 넣지 않는다.
            return None

        artifact = CatalogedArtifact(
            storage_uri=clip.storage_uri,
            sha256=digest,
            byte_size=clip.clip_path.stat().st_size,
            camera_id=clip.camera_id,
            started_at_ms=clip.started_at_ms,
            ended_at_ms=clip.ended_at_ms,
            job_id=clip.job_id,
            job_step_id=clip.job_step_id,
            incident_id=clip.incident_id,
        )
        self._sink.insert_artifact(artifact.as_artifact_row())
        return artifact


def sha256_file(path: Path, *, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ARTIFACT_TYPE",
    "ArtifactSink",
    "CONTINUOUS_RECORDING_ENABLED",
    "CatalogedArtifact",
    "EventClip",
    "EventClipCatalog",
    "EventClipError",
    "sha256_file",
]
