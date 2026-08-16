"""Automatic bottleneck approach leases at the two 0.2 m diameter passages."""

import pytest

from control_tower.rmf_adapter.bottleneck import (
    BOTTLENECK_EXECUTION_RADIUS_M,
    BOTTLENECK_SOURCE_DIAMETER_M,
    BottleneckCoordinator,
    BottleneckZone,
    RobotFootprint,
)


PINKY = RobotFootprint(
    radius_m=0.11,
    safety_margin_m=0.05,
    stopping_distance_m=0.09,
)


@pytest.fixture
def coordinator() -> BottleneckCoordinator:
    return BottleneckCoordinator(
        zones=(
            BottleneckZone("bottleneck_01", x=1.0, y=2.0),
            BottleneckZone("bottleneck_02", x=4.0, y=2.0),
        )
    )


def test_zone_geometry_comes_from_the_frozen_diameter() -> None:
    assert BOTTLENECK_SOURCE_DIAMETER_M == 0.2
    assert BOTTLENECK_EXECUTION_RADIUS_M == 0.1
    assert BottleneckZone("bottleneck_01", x=1.0, y=2.0).radius_m == 0.1


def test_approach_distance_sums_footprint_margin_and_stopping_distance() -> None:
    assert PINKY.approach_distance_m == pytest.approx(0.25)


def test_lease_is_required_before_the_footprint_crosses_the_zone(
    coordinator: BottleneckCoordinator,
) -> None:
    """The check happens on approach, not at the zone edge, and needs no waypoint."""
    # approach_distance_m is 0.25 and the zone radius is 0.1, so the lease is
    # needed from 0.35 m off the zone centre.
    far = coordinator.must_acquire_before(
        "bottleneck_01", robot_x=1.0, robot_y=2.36, footprint=PINKY
    )
    near = coordinator.must_acquire_before(
        "bottleneck_01", robot_x=1.0, robot_y=2.34, footprint=PINKY
    )

    assert far is False
    assert near is True
    assert coordinator.waiting_waypoints() == ()


def test_first_arrival_wins_bottleneck_without_priority_override(
    coordinator: BottleneckCoordinator,
) -> None:
    assert coordinator.request(
        "PK_02", "bottleneck_01", at_s=1, priority="normal"
    ).acquired
    denied = coordinator.request("PK_01", "bottleneck_01", at_s=2, priority="critical")
    assert denied.acquired is False
    assert denied.holder == "PK_02"
    assert denied.reason_code == "BOTTLENECK_OCCUPIED"


def test_holder_reentry_is_idempotent_and_other_zones_stay_free(
    coordinator: BottleneckCoordinator,
) -> None:
    coordinator.request("PK_02", "bottleneck_01", at_s=1)
    again = coordinator.request("PK_02", "bottleneck_01", at_s=3)
    other = coordinator.request("PK_01", "bottleneck_02", at_s=3)

    assert again.acquired is True
    assert again.holder == "PK_02"
    assert other.acquired is True


def test_unknown_zone_is_rejected_instead_of_being_created(
    coordinator: BottleneckCoordinator,
) -> None:
    with pytest.raises(KeyError):
        coordinator.request("PK_01", "bottleneck_99", at_s=1)


def test_detour_is_requested_only_after_fifteen_seconds_of_waiting(
    coordinator: BottleneckCoordinator,
) -> None:
    coordinator.request("PK_02", "bottleneck_01", at_s=0)
    coordinator.request("PK_01", "bottleneck_01", at_s=1)

    assert coordinator.poll("PK_01", "bottleneck_01", at_s=15.9).detour_requested is False
    late = coordinator.poll("PK_01", "bottleneck_01", at_s=16.0)
    assert late.detour_requested is True
    assert late.acquired is False


def test_invalid_detour_keeps_waiting_and_valid_detour_ends_the_wait(
    coordinator: BottleneckCoordinator,
) -> None:
    coordinator.request("PK_02", "bottleneck_01", at_s=0)
    coordinator.request("PK_01", "bottleneck_01", at_s=1)
    coordinator.poll("PK_01", "bottleneck_01", at_s=16.0)

    rejected = coordinator.record_detour("PK_01", "bottleneck_01", valid=False, at_s=17.0)
    assert rejected.detour_accepted is False
    assert coordinator.is_waiting("PK_01", "bottleneck_01") is True
    # A rejected detour must not restart the 15 s clock into a busy loop.
    assert coordinator.poll("PK_01", "bottleneck_01", at_s=17.1).detour_requested is False
    assert coordinator.poll("PK_01", "bottleneck_01", at_s=32.0).detour_requested is True

    accepted = coordinator.record_detour("PK_01", "bottleneck_01", valid=True, at_s=33.0)
    assert accepted.detour_accepted is True
    assert coordinator.is_waiting("PK_01", "bottleneck_01") is False


def test_lease_releases_only_when_the_whole_footprint_plus_margin_exits(
    coordinator: BottleneckCoordinator,
) -> None:
    coordinator.request("PK_02", "bottleneck_01", at_s=0)

    # Trailing edge still inside zone + footprint + margin (0.1 + 0.11 + 0.05).
    still_inside = coordinator.release(
        "PK_02", "bottleneck_01", robot_x=1.0, robot_y=2.25, footprint=PINKY
    )
    assert still_inside is False
    assert coordinator.holder("bottleneck_01") == "PK_02"

    cleared = coordinator.release(
        "PK_02", "bottleneck_01", robot_x=1.0, robot_y=2.27, footprint=PINKY
    )
    assert cleared is True
    assert coordinator.holder("bottleneck_01") == ""


def test_emergency_stop_inside_the_zone_retains_the_lease(
    coordinator: BottleneckCoordinator,
) -> None:
    coordinator.request("PK_02", "bottleneck_01", at_s=0)
    coordinator.hold("PK_02", "bottleneck_01", reason_code="EMERGENCY_STOP")

    assert coordinator.holder("bottleneck_01") == "PK_02"
    blocked = coordinator.request("PK_01", "bottleneck_01", at_s=5)
    assert blocked.acquired is False
    # Even a geometrically clear pose cannot release a held lease.
    assert (
        coordinator.release(
            "PK_02", "bottleneck_01", robot_x=1.0, robot_y=9.0, footprint=PINKY
        )
        is False
    )

    coordinator.resume("PK_02", "bottleneck_01")
    assert (
        coordinator.release(
            "PK_02", "bottleneck_01", robot_x=1.0, robot_y=9.0, footprint=PINKY
        )
        is True
    )


def test_release_by_a_non_holder_never_frees_the_zone(
    coordinator: BottleneckCoordinator,
) -> None:
    coordinator.request("PK_02", "bottleneck_01", at_s=0)
    assert (
        coordinator.release(
            "PK_01", "bottleneck_01", robot_x=1.0, robot_y=9.0, footprint=PINKY
        )
        is False
    )
    assert coordinator.holder("bottleneck_01") == "PK_02"


def test_waiting_robot_takes_the_zone_in_first_arrival_order_after_release(
    coordinator: BottleneckCoordinator,
) -> None:
    coordinator.request("PK_02", "bottleneck_01", at_s=0)
    coordinator.request("PK_01", "bottleneck_01", at_s=1, priority="critical")
    coordinator.release("PK_02", "bottleneck_01", robot_x=1.0, robot_y=9.0, footprint=PINKY)

    assert coordinator.request("PK_01", "bottleneck_01", at_s=6).acquired is True
