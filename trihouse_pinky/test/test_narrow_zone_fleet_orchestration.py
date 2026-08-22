"""Fleet가 일반 Nav2와 협로 규칙 주행을 선택하는 순수 경계 계약."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


PINKY = Path(__file__).resolve().parents[1]
REPOSITORY = PINKY.parent
sys.path.insert(0, str(PINKY / "trihouse_pinky_docking"))
sys.path.insert(0, str(PINKY / "trihouse_pinky_fleet"))

from trihouse_pinky_docking.narrow_zone import (  # noqa: E402
    EXIT,
    NarrowZoneController,
    Pose2D,
    load_narrow_zones,
)
from trihouse_pinky_fleet.narrow_zone_routing import (  # noqa: E402
    departure_profile,
    select_approach,
)


PROFILE_FILE = REPOSITORY / "config" / "narrow_zones.new_map_2.yaml"


def _profiles():
    return load_narrow_zones(
        yaml.safe_load(PROFILE_FILE.read_text(encoding="utf-8")),
        map_name="new_map_2",
    )


def test_an_ordinary_destination_keeps_the_requested_nav2_target() -> None:
    requested = Pose2D(0.25, -0.50, 1.2)

    decision = select_approach(_profiles(), "packing_station_loading_dock_01", requested)

    assert decision.allowed is True
    assert decision.profile is None
    assert decision.nav_target == requested


def test_a_warehouse_is_rejected_when_the_profile_catalog_is_missing() -> None:
    decision = select_approach(
        {},
        "frozen_storage_loading_dock_01",
        Pose2D(1.331, -0.815, -1.572),
    )

    assert decision.allowed is False
    assert decision.reason_code == "NARROW_PROFILE_MISSING"
    assert decision.nav_target is None


def test_a_charger_profile_only_controls_departure_not_the_return_nav2_goal() -> None:
    requested = Pose2D(0.0570244747, 0.1949666005, 0.1093261667)

    decision = select_approach(_profiles(), "charging_station_01", requested)

    assert decision.allowed is True
    assert decision.profile is None
    assert decision.nav_target == requested


def test_a_ready_warehouse_uses_entry_instead_of_the_final_dock() -> None:
    profiles = _profiles()
    frozen = profiles["frozen_storage_loading_dock_01"]
    # 이 테스트는 routing만 보므로 실기 exit 검증 상태를 완료시킨 복사본을 사용한다.
    ready = frozen.with_measurement(exit=True)
    profiles[ready.destination_code] = ready

    decision = select_approach(
        profiles,
        ready.destination_code,
        Pose2D(ready.dock_target.x, ready.dock_target.y, ready.dock_target.yaw),
    )

    assert decision.allowed is True
    assert decision.profile == ready
    assert decision.nav_target == ready.entry_pose
    assert decision.nav_target != ready.dock_target


def test_an_unmeasured_warehouse_is_rejected_instead_of_falling_back_to_nav2() -> None:
    requested_final_dock = Pose2D(1.3314581184, -0.8149269956, -1.572140)

    decision = select_approach(
        _profiles(),
        "frozen_storage_loading_dock_01",
        requested_final_dock,
    )

    assert decision.allowed is False
    assert decision.reason_code == "NARROW_PROFILE_UNMEASURED"
    assert decision.nav_target is None


def test_explicit_calibration_may_approach_a_structurally_complete_candidate() -> None:
    decision = select_approach(
        _profiles(),
        "frozen_storage_loading_dock_01",
        Pose2D(1.3314581184, -0.8149269956, -1.572140),
        calibration=True,
    )

    assert decision.allowed is True
    assert decision.profile is not None
    assert decision.nav_target == decision.profile.entry_pose


def test_a_disabled_warehouse_is_rejected_instead_of_disappearing() -> None:
    decision = select_approach(
        _profiles(),
        "ambient_storage_loading_dock_01",
        Pose2D(1.0, 1.0, 0.0),
    )

    assert decision.allowed is False
    assert decision.reason_code == "NARROW_PROFILE_DISABLED"
    assert decision.nav_target is None


def test_a_robot_docked_in_a_zone_must_depart_before_any_new_nav2_goal() -> None:
    profiles = _profiles()
    frozen = profiles["frozen_storage_loading_dock_01"]
    assert frozen.dock_target is not None

    departure = departure_profile(profiles, frozen.dock_target)

    assert departure == frozen
    assert departure.exit_target == frozen.entry_pose


def test_a_measured_charger_exit_is_operational_even_though_return_uses_nav2() -> None:
    profiles = _profiles()
    charger = profiles["charging_station_01"]
    assert charger.entry_pose is not None

    departure = departure_profile(profiles, charger.entry_pose)
    controller = NarrowZoneController(departure, direction=EXIT)

    assert departure == charger
    assert charger.approach_required is False
    assert charger.direction_readiness_code(EXIT) == "READY"
    assert controller.begin(charger.entry_pose, now_s=0.0) is True


def test_a_robot_outside_every_zone_needs_no_rule_departure() -> None:
    assert departure_profile(_profiles(), Pose2D(5.0, 5.0, 0.0)) is None
