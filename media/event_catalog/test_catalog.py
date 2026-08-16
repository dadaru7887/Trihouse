"""완료된 fixture 클립만 artifacts에 정확히 한 번 등록된다."""

import hashlib
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from media.event_catalog.catalog import (  # noqa: E402
    ARTIFACT_TYPE,
    CONTINUOUS_RECORDING_ENABLED,
    EventClip,
    EventClipCatalog,
    EventClipError,
    sha256_file,
)


class FakeSink:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def insert_artifact(self, row: dict) -> int:
        self.rows.append(row)
        return len(self.rows)

    def artifact_exists(self, *, sha256: str, storage_uri: str) -> bool:
        return any(
            row["sha256"] == sha256 and row["storage_uri"] == storage_uri
            for row in self.rows
        )


@pytest.fixture
def clip_file(tmp_path: Path) -> Path:
    path = tmp_path / "incident-1.mp4"
    path.write_bytes(b"fixture clip bytes")
    return path


def _clip(path: Path, **overrides) -> EventClip:
    payload = {
        "clip_path": path,
        "storage_uri": "s3://trihouse-p0/events/incident-1.mp4",
        "camera_id": "CAM-PK-01",
        "started_at_ms": 1_786_500_000_000,
        "ended_at_ms": 1_786_500_012_000,
        "job_id": 7,
        "job_step_id": 11,
        "incident_id": 3,
    }
    payload.update(overrides)
    return EventClip(**payload)


def test_p0_does_not_enable_continuous_six_stream_recording() -> None:
    assert CONTINUOUS_RECORDING_ENABLED is False


def test_completed_clip_is_hashed_and_related_to_job_step_and_incident(
    clip_file: Path,
) -> None:
    sink = FakeSink()

    artifact = EventClipCatalog(sink).catalog(_clip(clip_file))

    assert artifact is not None
    assert artifact.sha256 == hashlib.sha256(b"fixture clip bytes").hexdigest()
    assert artifact.byte_size == len(b"fixture clip bytes")

    row = sink.rows[0]
    assert row["artifact_type"] == ARTIFACT_TYPE
    assert row["storage_uri"] == "s3://trihouse-p0/events/incident-1.mp4"
    assert row["device_id"] == "CAM-PK-01"
    assert row["job_id"] == 7
    assert row["job_step_id"] == 11
    assert row["event_id"] == 3
    assert row["metadata"]["started_at_ms"] == 1_786_500_000_000
    assert row["metadata"]["ended_at_ms"] == 1_786_500_012_000
    assert row["metadata"]["duration_ms"] == 12_000
    assert row["metadata"]["capture_mode"] == "event_fixture"


def test_an_incomplete_clip_is_never_cataloged(clip_file: Path) -> None:
    sink = FakeSink()

    with pytest.raises(EventClipError, match="completed"):
        EventClipCatalog(sink).catalog(_clip(clip_file, completed=False))
    assert sink.rows == []


def test_a_missing_clip_file_is_reported_not_guessed(tmp_path: Path) -> None:
    sink = FakeSink()

    with pytest.raises(EventClipError, match="missing"):
        EventClipCatalog(sink).catalog(_clip(tmp_path / "absent.mp4"))
    assert sink.rows == []


def test_the_same_clip_is_registered_exactly_once(clip_file: Path) -> None:
    sink = FakeSink()
    catalog = EventClipCatalog(sink)

    first = catalog.catalog(_clip(clip_file))
    replay = catalog.catalog(_clip(clip_file))

    assert first is not None
    assert replay is None
    assert len(sink.rows) == 1


def test_a_different_uri_for_the_same_bytes_is_its_own_artifact(
    clip_file: Path,
) -> None:
    sink = FakeSink()
    catalog = EventClipCatalog(sink)

    catalog.catalog(_clip(clip_file))
    other = catalog.catalog(
        _clip(clip_file, storage_uri="s3://trihouse-p0/events/incident-1-copy.mp4")
    )

    assert other is not None
    assert len(sink.rows) == 2


def test_clip_time_range_must_be_ordered(clip_file: Path) -> None:
    with pytest.raises(EventClipError, match="end after it starts"):
        _clip(clip_file, ended_at_ms=1_786_500_000_000)
    with pytest.raises(EventClipError, match="positive"):
        _clip(clip_file, started_at_ms=0)


def test_camera_and_uri_are_mandatory_relations(clip_file: Path) -> None:
    with pytest.raises(EventClipError, match="camera_id"):
        _clip(clip_file, camera_id="  ")
    with pytest.raises(EventClipError, match="storage_uri"):
        _clip(clip_file, storage_uri="")


def test_hash_is_streamed_and_matches_whole_file(tmp_path: Path) -> None:
    payload = b"x" * (3 * (1 << 20) + 7)
    path = tmp_path / "large.mp4"
    path.write_bytes(payload)

    assert sha256_file(path) == hashlib.sha256(payload).hexdigest()
