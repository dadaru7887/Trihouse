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


def test_unmeasured_ambient_and_chilled_fail_closed() -> None:
    profiles = _profiles()
    for destination in (
        "ambient_storage_loading_dock_01",
        "chilled_storage_loading_dock_01",
    ):
        assert profiles[destination].executable is False
        assert profiles[destination].readiness_code == "NARROW_PROFILE_DISABLED"


def test_frozen_keeps_todays_entry_dock_and_distinct_exit_target() -> None:
    frozen = _profiles()[FROZEN]

    assert frozen.entry_pose is not None
    assert (frozen.entry_pose.x, frozen.entry_pose.y, frozen.entry_pose.yaw) == pytest.approx(
        (1.1792881155, -1.1896842748, 0.0109381190)
    )
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
