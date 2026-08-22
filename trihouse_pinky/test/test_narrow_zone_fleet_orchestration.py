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
    entry_handoff_reached,
    select_approach,
)


PROFILE_FILE = REPOSITORY / "config" / "narrow_zones.new_map_2.yaml"
CHARGING_DEPARTURE = "charging_narrow_departure"


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


def test_an_unmeasured_warehouse_is_rejected_instead_of_disappearing() -> None:
    decision = select_approach(
        _profiles(),
        "ambient_storage_loading_dock_01",
        Pose2D(1.0, 1.0, 0.0),
    )

    assert decision.allowed is False
    assert decision.reason_code == "NARROW_PROFILE_UNMEASURED"
    assert decision.nav_target is None


def test_a_robot_docked_in_a_zone_must_depart_before_any_new_nav2_goal() -> None:
    profiles = _profiles()
    frozen = profiles["frozen_storage_loading_dock_01"]
    assert frozen.dock_target is not None

    departure = departure_profile(profiles, frozen.dock_target)

    assert departure == frozen
    assert departure.exit_target == frozen.entry_pose


def test_two_start_waypoints_share_one_measured_charging_departure() -> None:
    profiles = _profiles()
    shared = profiles[CHARGING_DEPARTURE]

    for start in (Pose2D(0.171, 0.202, 0.0), Pose2D(0.076, -0.013, 0.0)):
        departure = departure_profile(profiles, start)
        assert departure == shared
        controller = NarrowZoneController(departure, direction=EXIT)
        assert controller.begin(start, now_s=0.0) is True

    assert shared.approach_required is False
    assert shared.direction_readiness_code(EXIT) == "READY"
    assert tuple((step.kind, step.value) for step in shared.exit) == (("straight", 0.7),)
    assert shared.exit_target == Pose2D(0.7992961442, 0.0854053105, 0.0923642279)


def test_charging_departure_trigger_uses_a_point_three_tenths_from_either_start() -> None:
    profiles = _profiles()

    assert departure_profile(profiles, Pose2D(0.171 + 0.299, 0.202, 1.2)) is profiles[
        CHARGING_DEPARTURE
    ]
    assert departure_profile(profiles, Pose2D(0.076, -0.013 - 0.299, -2.0)) is profiles[
        CHARGING_DEPARTURE
    ]


def test_charging_departure_stops_as_soon_as_the_measured_exit_radius_is_reached() -> None:
    shared = _profiles()[CHARGING_DEPARTURE]
    start = Pose2D(0.171, 0.202, -0.18)
    assert shared.exit_target is not None
    controller = NarrowZoneController(shared, direction=EXIT)

    assert controller.begin(start, now_s=0.0) is True
    command = controller.advance(shared.exit_target, now_s=1.0)

    assert command.is_zero
    assert controller.is_complete


def test_a_robot_outside_every_zone_needs_no_rule_departure() -> None:
    assert departure_profile(_profiles(), Pose2D(5.0, 5.0, 0.0)) is None


def test_nav2_handoff_uses_the_entry_zone_not_the_docked_zone() -> None:
    """도크 zone까지 Nav2가 들어간 뒤에야 전환되는 결함을 잡는다."""
    frozen = _profiles()["frozen_storage_loading_dock_01"]

    assert entry_handoff_reached(
        frozen, Pose2D(1.10, -1.19, -2.0)
    ) is True
    assert entry_handoff_reached(
        frozen, Pose2D(1.3314581184, -0.8149269956, -1.572140)
    ) is False
