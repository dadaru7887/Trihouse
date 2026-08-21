"""지도별 ArUco 도킹 프로필의 안전한 적재 계약."""

import sys
from pathlib import Path

import pytest


PINKY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PINKY / "trihouse_pinky_docking"))

from trihouse_pinky_docking.marker_profiles import (  # noqa: E402
    MarkerProfileError,
    load_marker_profiles,
)


def _write(tmp_path, body):
    path = tmp_path / "markers.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_verified_profile_loads_every_motion_safety_value(tmp_path) -> None:
    path = _write(tmp_path, """
map_name: new_map_2
docks:
  ambient_storage_loading_dock_01:
    verified: true
    marker_id: '2'
    minimum_confidence: 0.85
    stable_observations: 3
    observation_timeout_s: 0.4
    standoff_m: 0.52
    distance_tolerance_m: 0.025
    bearing_tolerance_rad: 0.035
    turn_direction: 1
    reverse_distance_m: 0.30
    activation_x_m: 1.25
    activation_y_m: -0.50
    activation_radius_m: 0.20
""")

    profiles = load_marker_profiles(path, map_name="new_map_2")
    profile = profiles["ambient_storage_loading_dock_01"]
    assert profile.marker_id == "2"
    assert profile.minimum_confidence == 0.85
    assert profile.turn_direction == 1
    assert profile.reverse_distance_m == 0.30
    assert profile.activation_x_m == 1.25
    assert profile.activation_radius_m == 0.20


def test_unverified_profile_is_not_returned_as_executable(tmp_path) -> None:
    path = _write(tmp_path, """
map_name: new_map_2
docks:
  frozen_storage_loading_dock_01:
    verified: false
    marker_id: '0'
""")
    assert load_marker_profiles(path, map_name="new_map_2") == {}


def test_profile_for_another_map_or_missing_measurement_is_rejected(tmp_path) -> None:
    wrong_map = _write(tmp_path, "map_name: old_map\ndocks: {}\n")
    with pytest.raises(MarkerProfileError, match="지도"):
        load_marker_profiles(wrong_map, map_name="new_map_2")

    incomplete = _write(tmp_path, """
map_name: new_map_2
docks:
  chilled_storage_loading_dock_01:
    verified: true
    marker_id: '1'
""")
    with pytest.raises(MarkerProfileError, match="실측값"):
        load_marker_profiles(incomplete, map_name="new_map_2")
