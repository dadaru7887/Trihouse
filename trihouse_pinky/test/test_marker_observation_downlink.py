"""FMS가 내린 camera-frame ArUco 관측의 Pinky 경계 검증."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "trihouse_pinky_fleet"))

from trihouse_pinky_fleet.protocol import ProtocolError, parse_marker_observation  # noqa: E402


def _payload(**overrides):
    payload = {
        "type": "marker_observation",
        "camera_id": "CAM-PK-02",
        "marker_family": "DICT_5X5_50",
        "marker_id": "0",
        "translation_m": {"x": 0.4, "y": 0.02, "z": 0.8},
        "confidence": 0.9,
        "ttl_ms": 250,
        "observed_at_ms": 1000,
    }
    payload.update(overrides)
    return payload


def test_marker_observation_preserves_camera_frame_translation() -> None:
    observation = parse_marker_observation(_payload())
    assert observation.camera_id == "CAM-PK-02"
    assert observation.translation_m == (0.4, 0.02, 0.8)


@pytest.mark.parametrize(
    "override",
    (
        {"marker_family": "DICT_4X4_50"},
        {"translation_m": {"x": 0.4, "y": 0.02}},
        {"ttl_ms": 0},
    ),
)
def test_marker_observation_rejects_unsafe_or_incomplete_input(override) -> None:
    with pytest.raises(ProtocolError):
        parse_marker_observation(_payload(**override))
