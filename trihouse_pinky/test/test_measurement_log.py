"""Pinky JSONL 측정 기록기 테스트."""

import json
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "trihouse_pinky_fleet"
sys.path.insert(0, str(PACKAGE_ROOT))

from trihouse_pinky_fleet.measurement_log import MeasurementLogWriter  # noqa: E402


def test_pinky_writer_uses_the_shared_measurement_schema(tmp_path):
    writer = MeasurementLogWriter(
        root=tmp_path, run_id="poc-01", component="pinky_gateway"
    )

    assert writer.write("battery_telemetry_PK-01", {"robot_id": "PK-01"})

    record = json.loads(
        (tmp_path / "poc-01" / "battery_telemetry_PK-01.jsonl")
        .read_text()
        .strip()
    )
    assert record["schema_version"] == 1
    assert record["run_id"] == "poc-01"
    assert record["record_type"] == "battery_telemetry_PK-01"
    assert record["robot_id"] == "PK-01"


def test_pinky_writer_rejects_unsafe_stream_name(tmp_path):
    writer = MeasurementLogWriter(
        root=tmp_path, run_id="poc-01", component="pinky_gateway"
    )
    with pytest.raises(ValueError):
        writer.write("../outside", {"value": 1})
