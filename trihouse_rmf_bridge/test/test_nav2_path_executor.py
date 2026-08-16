"""배정된 Pinky만 Nav2 후보 경로를 계산하고 RMF 승인 뒤 추종한다."""

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

from control_tower.rmf_adapter.path_schedule import (
    AssignedPathRequest,
    PathScheduleCoordinator,
)
from trihouse_rmf_bridge.nav2_path_executor import (
    AssignmentMismatch,
    FollowOutcome,
    Nav2PathExecutor,
    Nav2PathUnavailable,
)


MAP_REVISION = "trihouse_test_01:7"
STRAIGHT = ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (4.0, 0.0, 0.0))


def _request(robot_name: str = "PK_01") -> AssignedPathRequest:
    return AssignedPathRequest(
        job_step_id=7,
        assignment_revision=4,
        robot_name=robot_name,
        map_revision=MAP_REVISION,
        goal_pose=(4.0, 0.0, 0.0),
    )


class FakeComputeClient:
    """Nav2 `ComputePathToPose`. 계산만 하고 절대 움직이지 않는다."""

    def __init__(self, poses=STRAIGHT, travel_time_s: float = 8.0, ready: bool = True):
        self.poses = poses
        self.travel_time_s = travel_time_s
        self.ready = ready
        self.calls: list[dict] = []
        self.excluded: list[tuple[float, float, float]] = []

    def server_is_ready(self) -> bool:
        return self.ready

    def compute_path_to_pose(self, *, goal_pose, map_revision, exclude_zones=()):
        self.calls.append(
            {
                "goal_pose": goal_pose,
                "map_revision": map_revision,
                "exclude_zones": tuple(exclude_zones),
            }
        )
        self.excluded.extend(exclude_zones)
        if self.poses is None:
            return None
        return tuple(self.poses), self.travel_time_s


class FakeFollowClient:
    def __init__(self, outcome=FollowOutcome.SUCCEEDED, ready: bool = True, on_follow=None):
        self.outcome = outcome
        self.ready = ready
        self.followed: list[tuple] = []
        self.cancels = 0
        self.on_follow = on_follow
        self.observed: list[object] = []

    def server_is_ready(self) -> bool:
        return self.ready

    def follow_path(self, poses):
        self.followed.append(tuple(poses))
        if self.on_follow is not None:
            self.observed.append(self.on_follow())
        return self.outcome

    def cancel(self) -> None:
        self.cancels += 1


def _executor(
    *,
    robot_name="PK_01",
    compute=None,
    follow=None,
    schedule=None,
    clock_values=None,
):
    times = list(clock_values or [0.0] * 32)
    return Nav2PathExecutor(
        robot_name=robot_name,
        compute_client=compute or FakeComputeClient(),
        follow_client=follow or FakeFollowClient(),
        schedule=schedule if schedule is not None else PathScheduleCoordinator(),
        clock=lambda: times.pop(0) if times else 0.0,
    )


# --- compute ------------------------------------------------------------------


def test_compute_plans_without_moving_the_robot() -> None:
    compute, follow = FakeComputeClient(), FakeFollowClient()
    executor = _executor(compute=compute, follow=follow)

    path = executor.compute(_request())

    assert path.poses == STRAIGHT
    assert path.travel_time_s == 8.0
    assert path.request.robot_name == "PK_01"
    assert compute.calls[0]["goal_pose"] == (4.0, 0.0, 0.0)
    assert compute.calls[0]["map_revision"] == MAP_REVISION
    assert follow.followed == []


def test_path_hash_is_deterministic_and_pose_sensitive() -> None:
    first = _executor().compute(_request())
    same = _executor().compute(_request())
    other = _executor(
        compute=FakeComputeClient(poses=((0.0, 0.0, 0.0), (4.0, 1.0, 0.0)))
    ).compute(_request())

    assert first.path_hash == same.path_hash
    assert first.path_hash != other.path_hash


def test_executor_refuses_a_command_addressed_to_another_pinky() -> None:
    compute = FakeComputeClient()
    executor = _executor(robot_name="PK_02", compute=compute)

    with pytest.raises(AssignmentMismatch, match="ASSIGNMENT_MISMATCH"):
        executor.compute(_request("PK_01"))
    assert compute.calls == []


def test_missing_nav2_planner_or_empty_plan_is_reported_not_guessed() -> None:
    with pytest.raises(Nav2PathUnavailable):
        _executor(compute=FakeComputeClient(ready=False)).compute(_request())
    with pytest.raises(Nav2PathUnavailable):
        _executor(compute=FakeComputeClient(poses=None)).compute(_request())


def test_detour_plan_excludes_the_occupied_bottleneck_region() -> None:
    compute = FakeComputeClient()
    executor = _executor(compute=compute)

    executor.compute(_request(), exclude_zones=((1.0, 2.0, 0.1),))

    assert compute.calls[0]["exclude_zones"] == ((1.0, 2.0, 0.1),)


# --- follow -------------------------------------------------------------------


def test_follow_registers_the_itinerary_and_only_then_moves() -> None:
    schedule = PathScheduleCoordinator()
    follow = FakeFollowClient(on_follow=lambda: schedule.registration("PK_01"))
    executor = _executor(follow=follow, schedule=schedule)
    path = executor.compute(_request())

    result = executor.follow(path)

    # The itinerary is registered for the whole time FollowPath is running.
    assert follow.observed[0].path_hash == path.path_hash
    assert follow.observed[0].map_revision == MAP_REVISION
    assert follow.followed == [STRAIGHT]
    assert result.reached is True
    assert result.reason_code == "REACHED"
    assert result.path_hash == path.path_hash
    # A finished route must not keep occupying the schedule.
    assert schedule.registration("PK_01") is None


def test_conflicting_itinerary_holds_the_robot_before_follow_path() -> None:
    schedule = PathScheduleCoordinator()
    follow = FakeFollowClient()
    executor = _executor(follow=follow, schedule=schedule)
    path = executor.compute(_request())

    # An earlier participant already owns the same corridor at the same time.
    blocker = _executor(
        robot_name="PK_02",
        compute=FakeComputeClient(poses=((4.0, 0.0, 0.0), (0.0, 0.0, 0.0))),
        schedule=schedule,
    )
    schedule.register(blocker.compute(_request("PK_02")), start_time_s=0.0)

    result = executor.follow(path)

    assert follow.followed == []
    assert result.reached is False
    assert result.reason_code == "CONFLICTING_ITINERARY"


def test_replan_holds_releases_the_override_and_allows_re_registration() -> None:
    schedule = PathScheduleCoordinator()
    follow = FakeFollowClient(outcome=FollowOutcome.REPLAN_REQUIRED)
    executor = _executor(follow=follow, schedule=schedule)
    path = executor.compute(_request())
    schedule.acquire_override("PK_01", reason_code="FOLLOWING")

    result = executor.follow(path)

    assert result.reached is False
    assert result.reason_code == "NAV2_REPLAN_REQUIRED"
    assert result.path_hash == path.path_hash
    assert follow.cancels == 1
    assert schedule.registration("PK_01") is None
    assert schedule.override_holder() == ""

    replanned = executor.compute(_request())
    executor.follow(replanned)
    assert schedule.override_holder() == ""


def test_schedule_mismatch_cancels_instead_of_following_a_stale_path() -> None:
    schedule = PathScheduleCoordinator()
    follow = FakeFollowClient()
    executor = _executor(follow=follow, schedule=schedule)
    stale = executor.compute(_request())
    fresh = _executor(
        compute=FakeComputeClient(poses=((0.0, 0.0, 0.0), (4.0, 3.0, 0.0))),
        schedule=schedule,
    ).compute(_request())
    schedule.register(fresh, start_time_s=0.0)

    result = executor.follow(stale, register=False)

    assert follow.followed == []
    assert result.reached is False
    assert result.reason_code == "PATH_SCHEDULE_MISMATCH"


def test_aborted_follow_reports_its_reason_and_frees_the_route() -> None:
    schedule = PathScheduleCoordinator()
    executor = _executor(
        follow=FakeFollowClient(outcome=FollowOutcome.ABORTED), schedule=schedule
    )

    result = executor.follow(executor.compute(_request()))

    assert result.reached is False
    assert result.reason_code == "NAV2_FOLLOW_ABORTED"
    assert schedule.registration("PK_01") is None


def test_missing_follow_server_never_reports_a_reached_goal() -> None:
    executor = _executor(follow=FakeFollowClient(ready=False))

    result = executor.follow(executor.compute(_request()))

    assert result.reached is False
    assert result.reason_code == "NAV2_FOLLOW_UNAVAILABLE"
