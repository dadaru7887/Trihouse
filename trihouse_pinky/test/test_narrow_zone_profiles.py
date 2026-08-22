"""배포되는 new_map_2 창고 profile의 실측/readiness 계약."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml


PINKY = Path(__file__).resolve().parents[1]
REPOSITORY = PINKY.parent
sys.path.insert(0, str(PINKY / "trihouse_pinky_docking"))

from trihouse_pinky_docking.narrow_zone import (  # noqa: E402
    ENTER,
    EXIT,
    load_narrow_zones,
)


PROFILE_FILE = REPOSITORY / "config" / "narrow_zones.new_map_2.yaml"
AMBIENT = "ambient_storage_loading_dock_01"
CHILLED = "chilled_storage_loading_dock_01"
FROZEN = "frozen_storage_loading_dock_01"


def _profiles():
    document = yaml.safe_load(PROFILE_FILE.read_text(encoding="utf-8"))
    return load_narrow_zones(document, map_name="new_map_2")


def test_every_storage_warehouse_remains_visible_in_the_catalog() -> None:
    assert {
        "ambient_storage_loading_dock_01",
        "chilled_storage_loading_dock_01",
        FROZEN,
    } <= set(_profiles())


def test_ambient_and_chilled_load_the_rule_values_as_calibration_only() -> None:
    profiles = _profiles()
    expected = {
        AMBIENT: {
            "entry": (1.010244055594586, 0.9167344977253539, -0.08675495954950327),
            "dock": (1.293481094178777, 1.0156120986977553, -2.805721254488808),
            "enter": (("rotate", -2.805721254488808), ("straight", -0.30)),
        },
        CHILLED: {
            "entry": (1.1013315221281241, -0.10045055614140724, 3.1029342608092607),
            "dock": (1.3263418779273253, -0.2988701614809928, 2.4189105956431427),
            "enter": (("rotate", 2.4189105956431427), ("straight", -0.30)),
        },
    }

    for destination, wanted in expected.items():
        profile = profiles[destination]
        assert profile.marker_id is None
        assert profile.entry_pose is not None
        assert (profile.entry_pose.x, profile.entry_pose.y, profile.entry_pose.yaw) == pytest.approx(
            wanted["entry"]
        )
        assert profile.entry_zone is not None
        assert (profile.entry_zone.length, profile.entry_zone.width) == pytest.approx(
            (0.05, 0.20)
        )
        assert profile.dock_target is not None
        assert (profile.dock_target.x, profile.dock_target.y, profile.dock_target.yaw) == pytest.approx(
            wanted["dock"]
        )
        assert tuple(step.kind for step in profile.enter) == tuple(
            kind for kind, _ in wanted["enter"]
        )
        assert tuple(step.value for step in profile.enter) == pytest.approx(
            tuple(value for _, value in wanted["enter"])
        )
        assert profile.exit_target is not None
        assert (profile.exit_target.x, profile.exit_target.y, profile.exit_target.yaw) == pytest.approx(
            (wanted["entry"][0], wanted["entry"][1], -3.130293455959265)
        )
        assert profile.calibration_ready(ENTER) is True
        assert profile.calibration_ready(EXIT) is True
        assert profile.executable is False
        assert profile.readiness_code == "NARROW_PROFILE_UNMEASURED"


def test_frozen_keeps_todays_entry_dock_and_distinct_exit_target() -> None:
    frozen = _profiles()[FROZEN]

    assert frozen.entry_pose is not None
    assert (frozen.entry_pose.x, frozen.entry_pose.y, frozen.entry_pose.yaw) == pytest.approx(
        (1.1792881155, -1.1896842748, 0.0109381190)
    )
    assert frozen.entry_zone is not None
    assert (
        frozen.entry_zone.x,
        frozen.entry_zone.y,
        frozen.entry_zone.yaw,
        frozen.entry_zone.length,
        frozen.entry_zone.width,
    ) == pytest.approx((1.1792881155, -1.1896842748, 0.0109381190, 0.20, 0.20))
    assert frozen.dock_target is not None
    assert (frozen.dock_target.x, frozen.dock_target.y, frozen.dock_target.yaw) == pytest.approx(
        (1.3314581184, -0.8149269956, -1.572140)
    )
    assert frozen.exit_target == frozen.entry_pose
    assert frozen.enter != frozen.exit


def test_frozen_can_be_calibrated_but_not_operationally_assigned_until_exit_is_measured() -> None:
    frozen = _profiles()[FROZEN]

    assert frozen.calibration_ready(ENTER) is True
    assert frozen.calibration_ready(EXIT) is True
    assert frozen.measurement.exit is False
    assert frozen.executable is False
    assert frozen.readiness_code == "NARROW_PROFILE_UNMEASURED"
