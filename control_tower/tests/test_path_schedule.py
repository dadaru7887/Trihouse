"""Assigned-robot dispatch identity and Nav2 path scheduling under RMF."""

import pytest

from control_tower.rmf_adapter.path_schedule import (
    AssignedPathRequest,
    PathExecutionResult,
    PathScheduleCoordinator,
    PlannedNavPath,
    validate_assigned_command,
)
from control_tower.rmf_adapter.task_api import GoToPlaceRequest, build_dispatch_request


MAP_REVISION = "trihouse_test_01:7"


def _request(robot_name: str = "PK_01", *, step: int = 7) -> AssignedPathRequest:
    return AssignedPathRequest(
        job_step_id=step,
        assignment_revision=4,
        robot_name=robot_name,
        map_revision=MAP_REVISION,
        goal_pose=(4.0, 0.0, 0.0),
    )


def _straight_path(
    robot_name: str,
    *,
    start_x: float,
    end_x: float,
    y: float,
    travel_time_s: float = 4.0,
) -> PlannedNavPath:
    span = end_x - start_x
    poses = tuple(
        (start_x + span * index / 4.0, y, 0.0 if span > 0 else 3.141592653589793)
        for index in range(5)
    )
    return PlannedNavPath(
        request=_request(robot_name),
        poses=poses,
        travel_time_s=travel_time_s,
        path_hash=f"hash-{robot_name}-{start_x}-{end_x}-{y}",
    )


@pytest.fixture
def coordinator() -> PathScheduleCoordinator:
    return PathScheduleCoordinator()


# --- Step 3: the selected robot identity is mandatory end to end ---------------


def test_dispatch_contract_requires_assigned_robot() -> None:
    request = GoToPlaceRequest(
        request_id="r1",
        job_step_id=7,
        waypoint="ambient_storage_loading_dock_01",
        fleet_name="trihouse_pinky",
        robot_name="PK_01",
        request_time_ms=1,
    )
    assert request.robot_name == "PK_01"


def test_dispatch_request_without_a_robot_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="robot_name"):
        GoToPlaceRequest(
            request_id="r1",
            job_step_id=7,
            waypoint="ambient_storage_loading_dock_01",
            fleet_name="trihouse_pinky",
            robot_name="  ",
            request_time_ms=1,
        )


def test_built_dispatch_payload_pins_the_control_tower_robot() -> None:
    payload = build_dispatch_request(
        GoToPlaceRequest(
            request_id="r1",
            job_step_id=7,
            waypoint="ambient_storage_loading_dock_01",
            fleet_name="trihouse_pinky",
            robot_name="PK_02",
            request_time_ms=1,
        )
    )
    request = payload["request"]

    assert request["fleet_name"] == "trihouse_pinky"
    assert request["robot_name"] == "PK_02"
    assert "robot:PK_02" in request["labels"]


def test_adapter_with_another_name_rejects_the_command() -> None:
    accepted = validate_assigned_command(
        adapter_robot_name="PK_01", request=_request("PK_01")
    )
    refused = validate_assigned_command(
        adapter_robot_name="PK_02", request=_request("PK_01")
    )

    assert accepted.accepted is True
    assert refused.accepted is False
    assert refused.reason_code == "ASSIGNMENT_MISMATCH"


# --- Step 4: candidate path registration before any motion --------------------


def test_registration_converts_every_pose_to_a_timed_itinerary(
    coordinator: PathScheduleCoordinator,
) -> None:
    path = _straight_path("PK_01", start_x=0.0, end_x=4.0, y=0.0)
    registration = coordinator.register(path, start_time_s=10.0)

    assert registration.robot_name == "PK_01"
    assert registration.path_hash == path.path_hash
    assert registration.map_revision == MAP_REVISION
    assert len(registration.itinerary) == len(path.poses)
    assert registration.itinerary[0].t_s == pytest.approx(10.0)
    assert registration.itinerary[-1].t_s == pytest.approx(14.0)
    assert [point.t_s for point in registration.itinerary] == sorted(
        point.t_s for point in registration.itinerary
    )
    assert (registration.itinerary[0].x, registration.itinerary[0].y) == (0.0, 0.0)
    assert (registration.itinerary[-1].x, registration.itinerary[-1].y) == (4.0, 0.0)


def test_motion_is_refused_until_a_path_is_registered(
    coordinator: PathScheduleCoordinator,
) -> None:
    decision = coordinator.clearance("PK_01")

    assert decision.cleared is False
    assert decision.reason_code == "UNREGISTERED_PATH"
    assert coordinator.may_move("PK_01") is False


def test_head_on_itineraries_are_held_until_the_conflict_clears(
    coordinator: PathScheduleCoordinator,
) -> None:
    coordinator.register(
        _straight_path("PK_01", start_x=0.0, end_x=4.0, y=0.0), start_time_s=0.0
    )
    coordinator.register(
        _straight_path("PK_02", start_x=4.0, end_x=0.0, y=0.0), start_time_s=0.0
    )

    second = coordinator.clearance("PK_02")
    assert second.cleared is False
    assert second.reason_code == "CONFLICTING_ITINERARY"
    assert second.conflict_with == "PK_01"
    # The earlier registration keeps its clearance; only the later one waits.
    assert coordinator.clearance("PK_01").cleared is True

    coordinator.release("PK_01")
    assert coordinator.clearance("PK_02").cleared is True


def test_parallel_lanes_clear_both_robots(
    coordinator: PathScheduleCoordinator,
) -> None:
    coordinator.register(
        _straight_path("PK_01", start_x=0.0, end_x=4.0, y=0.0), start_time_s=0.0
    )
    coordinator.register(
        _straight_path("PK_02", start_x=0.0, end_x=4.0, y=5.0), start_time_s=0.0
    )

    assert coordinator.clearance("PK_01").cleared is True
    assert coordinator.clearance("PK_02").cleared is True


def test_same_corridor_at_a_later_time_does_not_conflict(
    coordinator: PathScheduleCoordinator,
) -> None:
    coordinator.register(
        _straight_path("PK_01", start_x=0.0, end_x=4.0, y=0.0), start_time_s=0.0
    )
    coordinator.register(
        _straight_path("PK_02", start_x=0.0, end_x=4.0, y=0.0), start_time_s=60.0
    )

    assert coordinator.clearance("PK_02").cleared is True


def test_execution_of_an_unregistered_hash_reports_schedule_mismatch(
    coordinator: PathScheduleCoordinator,
) -> None:
    path = _straight_path("PK_01", start_x=0.0, end_x=4.0, y=0.0)
    coordinator.register(path, start_time_s=0.0)

    assert coordinator.verify_execution("PK_01", path_hash=path.path_hash).cleared is True
    stale = coordinator.verify_execution("PK_01", path_hash="stale-hash")
    assert stale.cleared is False
    assert stale.reason_code == "PATH_SCHEDULE_MISMATCH"


def test_replan_releases_the_route_and_override_then_re_registers(
    coordinator: PathScheduleCoordinator,
) -> None:
    first = _straight_path("PK_01", start_x=0.0, end_x=4.0, y=0.0)
    coordinator.register(first, start_time_s=0.0)
    assert coordinator.acquire_override("PK_01", reason_code="REPLAN_REQUIRED") is True

    ticket = coordinator.hold_for_replan("PK_01", reason_code="NAV2_REPLAN_REQUIRED")

    assert ticket.robot_name == "PK_01"
    assert ticket.released_path_hash == first.path_hash
    assert ticket.reason_code == "NAV2_REPLAN_REQUIRED"
    assert coordinator.override_holder() == ""
    assert coordinator.registration("PK_01") is None
    assert coordinator.may_move("PK_01") is False

    second = _straight_path("PK_01", start_x=0.0, end_x=4.0, y=1.0)
    coordinator.register(second, start_time_s=5.0)
    assert coordinator.registration("PK_01").path_hash == second.path_hash
    assert coordinator.may_move("PK_01") is True


def test_only_one_robot_holds_a_stubborn_override_at_a_time(
    coordinator: PathScheduleCoordinator,
) -> None:
    assert coordinator.acquire_override("PK_01", reason_code="BOTTLENECK_WAIT") is True
    assert coordinator.acquire_override("PK_02", reason_code="BOTTLENECK_WAIT") is False
    assert coordinator.override_holder() == "PK_01"

    coordinator.release_override("PK_01")
    assert coordinator.acquire_override("PK_02", reason_code="BOTTLENECK_WAIT") is True
    assert coordinator.override_holder() == "PK_02"


def test_registering_another_robots_path_under_a_held_registration_is_isolated(
    coordinator: PathScheduleCoordinator,
) -> None:
    path = _straight_path("PK_01", start_x=0.0, end_x=4.0, y=0.0)
    coordinator.register(path, start_time_s=0.0)
    coordinator.release("PK_02")  # releasing an unknown robot is a no-op

    assert coordinator.registration("PK_01") is not None


def test_path_execution_result_carries_the_hash_that_actually_ran() -> None:
    result = PathExecutionResult(
        reached=False, reason_code="NAV2_REPLAN_REQUIRED", path_hash="hash-a"
    )

    assert result.reached is False
    assert result.reason_code == "NAV2_REPLAN_REQUIRED"
    assert result.path_hash == "hash-a"


def test_planned_path_rejects_an_empty_or_non_finite_pose_list() -> None:
    with pytest.raises(ValueError):
        PlannedNavPath(
            request=_request(), poses=(), travel_time_s=1.0, path_hash="hash"
        )
    with pytest.raises(ValueError):
        PlannedNavPath(
            request=_request(),
            poses=((0.0, 0.0, 0.0), (float("nan"), 1.0, 0.0)),
            travel_time_s=1.0,
            path_hash="hash",
        )
    with pytest.raises(ValueError):
        PlannedNavPath(
            request=_request(),
            poses=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
            travel_time_s=0.0,
            path_hash="hash",
        )
