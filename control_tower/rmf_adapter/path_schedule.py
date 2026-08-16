"""Control Tower가 배정한 로봇의 Nav2 후보 경로를 RMF 일정으로 등록한다.

P0 이동은 항상 세 단계를 거친다. Nav2 `ComputePathToPose`로 실제 경로를
계산하고(이 시점에는 움직이지 않는다), 모든 pose/시간을 배정된 RMF
participant itinerary로 변환해 등록하고, 충돌이 해소되어 clearance가 나온
뒤에야 `FollowPath`를 호출한다. 재계획이 필요하거나 실행 중인 경로 해시가
등록본과 다르면 보류하고 override handle을 반납한 뒤 다시 등록한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True)
class AssignedPathRequest:
    job_step_id: int
    assignment_revision: int
    robot_name: str
    map_revision: str
    goal_pose: tuple[float, float, float]

    def __post_init__(self) -> None:
        if self.job_step_id <= 0:
            raise ValueError("job_step_id must be positive")
        if self.assignment_revision <= 0:
            raise ValueError("assignment_revision must be positive")
        if not self.robot_name.strip():
            raise ValueError("robot_name is required")
        if not self.map_revision.strip():
            raise ValueError("map_revision is required")
        if len(self.goal_pose) != 3 or not all(
            math.isfinite(value) for value in self.goal_pose
        ):
            raise ValueError("goal_pose must be a finite (x, y, yaw) triple")


@dataclass(frozen=True)
class PlannedNavPath:
    request: AssignedPathRequest
    poses: tuple[tuple[float, float, float], ...]
    travel_time_s: float
    path_hash: str

    def __post_init__(self) -> None:
        if len(self.poses) < 2:
            raise ValueError("a planned path needs at least a start and a goal pose")
        for pose in self.poses:
            if len(pose) != 3 or not all(math.isfinite(value) for value in pose):
                raise ValueError("every pose must be a finite (x, y, yaw) triple")
        if not math.isfinite(self.travel_time_s) or self.travel_time_s <= 0:
            raise ValueError("travel_time_s must be positive")
        if not self.path_hash.strip():
            raise ValueError("path_hash is required")


@dataclass(frozen=True)
class PathExecutionResult:
    reached: bool
    reason_code: str
    path_hash: str


@dataclass(frozen=True)
class ItineraryPoint:
    t_s: float
    x: float
    y: float
    yaw: float


@dataclass(frozen=True)
class ScheduleRegistration:
    robot_name: str
    route_id: int
    path_hash: str
    map_revision: str
    assignment_revision: int
    itinerary: tuple[ItineraryPoint, ...]


@dataclass(frozen=True)
class ClearanceDecision:
    cleared: bool
    reason_code: str = ""
    conflict_with: str = ""


@dataclass(frozen=True)
class CommandAcceptance:
    accepted: bool
    reason_code: str = ""


@dataclass(frozen=True)
class ReplanTicket:
    robot_name: str
    released_path_hash: str
    reason_code: str


def validate_assigned_command(
    *, adapter_robot_name: str, request: AssignedPathRequest
) -> CommandAcceptance:
    """이름이 다른 adapter/worker는 명령을 실행하지 않고 거절한다."""
    if adapter_robot_name.strip() == request.robot_name:
        return CommandAcceptance(True)
    return CommandAcceptance(False, "ASSIGNMENT_MISMATCH")


class PathScheduleCoordinator:
    """등록된 itinerary들의 시공간 충돌을 해소하고 override를 단일화한다."""

    def __init__(
        self,
        *,
        conflict_radius_m: float = 0.35,
        sample_interval_s: float = 0.1,
    ) -> None:
        if conflict_radius_m <= 0 or sample_interval_s <= 0:
            raise ValueError("conflict radius and sample interval must be positive")
        self._conflict_radius_m = conflict_radius_m
        self._sample_interval_s = sample_interval_s
        self._lock = RLock()
        self._registrations: dict[str, ScheduleRegistration] = {}
        self._order: list[str] = []
        self._next_route_id = 1
        self._override_holder = ""
        self._override_reason = ""

    # --- 등록 -------------------------------------------------------------

    def register(
        self, path: PlannedNavPath, *, start_time_s: float
    ) -> ScheduleRegistration:
        """계산된 후보 경로의 모든 pose를 시간이 붙은 itinerary로 등록한다."""
        if not math.isfinite(start_time_s):
            raise ValueError("start_time_s must be finite")
        robot_name = path.request.robot_name
        itinerary = _timed_itinerary(path, start_time_s)
        with self._lock:
            registration = ScheduleRegistration(
                robot_name=robot_name,
                route_id=self._next_route_id,
                path_hash=path.path_hash,
                map_revision=path.request.map_revision,
                assignment_revision=path.request.assignment_revision,
                itinerary=itinerary,
            )
            self._next_route_id += 1
            if robot_name not in self._registrations:
                self._order.append(robot_name)
            self._registrations[robot_name] = registration
            return registration

    def registration(self, robot_name: str) -> ScheduleRegistration | None:
        with self._lock:
            return self._registrations.get(robot_name)

    def release(self, robot_name: str) -> None:
        with self._lock:
            if self._registrations.pop(robot_name, None) is not None:
                self._order.remove(robot_name)

    # --- clearance --------------------------------------------------------

    def clearance(self, robot_name: str) -> ClearanceDecision:
        """먼저 등록된 경로가 우선하며, 충돌이 남아 있으면 움직이지 않는다."""
        with self._lock:
            mine = self._registrations.get(robot_name)
            if mine is None:
                return ClearanceDecision(False, "UNREGISTERED_PATH")
            for other_name in self._order:
                if other_name == robot_name:
                    break
                other = self._registrations[other_name]
                if _itineraries_conflict(
                    mine.itinerary,
                    other.itinerary,
                    radius_m=self._conflict_radius_m,
                    step_s=self._sample_interval_s,
                ):
                    return ClearanceDecision(
                        False, "CONFLICTING_ITINERARY", conflict_with=other_name
                    )
            return ClearanceDecision(True)

    def may_move(self, robot_name: str) -> bool:
        return self.clearance(robot_name).cleared

    def verify_execution(self, robot_name: str, *, path_hash: str) -> ClearanceDecision:
        """실행 중인 경로 해시가 등록본과 다르면 보류 사유를 반환한다."""
        with self._lock:
            registration = self._registrations.get(robot_name)
            if registration is None:
                return ClearanceDecision(False, "UNREGISTERED_PATH")
            if registration.path_hash != path_hash:
                return ClearanceDecision(False, "PATH_SCHEDULE_MISMATCH")
            return ClearanceDecision(True)

    # --- stubborn override ------------------------------------------------

    def acquire_override(self, robot_name: str, *, reason_code: str) -> bool:
        """두 로봇이 동시에 stubborn override handle을 쥐지 못하게 한다."""
        with self._lock:
            if self._override_holder in ("", robot_name):
                self._override_holder = robot_name
                self._override_reason = reason_code
                return True
            return False

    def release_override(self, robot_name: str) -> None:
        with self._lock:
            if self._override_holder == robot_name:
                self._override_holder = ""
                self._override_reason = ""

    def override_holder(self) -> str:
        with self._lock:
            return self._override_holder

    def override_reason(self) -> str:
        with self._lock:
            return self._override_reason

    # --- 재계획 -----------------------------------------------------------

    def hold_for_replan(self, robot_name: str, *, reason_code: str) -> ReplanTicket:
        """경로를 취소하고 override handle을 반납한 뒤 재등록을 기다린다."""
        with self._lock:
            registration = self._registrations.get(robot_name)
            released = registration.path_hash if registration is not None else ""
            self.release(robot_name)
            self.release_override(robot_name)
            return ReplanTicket(
                robot_name=robot_name,
                released_path_hash=released,
                reason_code=reason_code,
            )


def _timed_itinerary(
    path: PlannedNavPath, start_time_s: float
) -> tuple[ItineraryPoint, ...]:
    """이동 거리 비율로 각 pose에 도달 시각을 부여한다."""
    cumulative = [0.0]
    for previous, current in zip(path.poses, path.poses[1:], strict=False):
        cumulative.append(
            cumulative[-1] + math.hypot(current[0] - previous[0], current[1] - previous[1])
        )
    total = cumulative[-1]
    points: list[ItineraryPoint] = []
    for pose, travelled in zip(path.poses, cumulative, strict=True):
        ratio = travelled / total if total > 0 else 0.0
        points.append(
            ItineraryPoint(
                t_s=start_time_s + path.travel_time_s * ratio,
                x=pose[0],
                y=pose[1],
                yaw=pose[2],
            )
        )
    if total <= 0:
        # 제자리 회전도 예약된 시간 구간을 점유한다.
        points[-1] = ItineraryPoint(
            t_s=start_time_s + path.travel_time_s,
            x=points[-1].x,
            y=points[-1].y,
            yaw=points[-1].yaw,
        )
    return tuple(points)


def _position_at(itinerary: tuple[ItineraryPoint, ...], t_s: float) -> tuple[float, float]:
    if t_s <= itinerary[0].t_s:
        return itinerary[0].x, itinerary[0].y
    if t_s >= itinerary[-1].t_s:
        return itinerary[-1].x, itinerary[-1].y
    for previous, current in zip(itinerary, itinerary[1:], strict=False):
        if previous.t_s <= t_s <= current.t_s:
            span = current.t_s - previous.t_s
            ratio = 0.0 if span <= 0 else (t_s - previous.t_s) / span
            return (
                previous.x + (current.x - previous.x) * ratio,
                previous.y + (current.y - previous.y) * ratio,
            )
    return itinerary[-1].x, itinerary[-1].y


def _itineraries_conflict(
    first: tuple[ItineraryPoint, ...],
    second: tuple[ItineraryPoint, ...],
    *,
    radius_m: float,
    step_s: float,
) -> bool:
    """겹치는 시간 구간을 균일 샘플링해 시공간 충돌을 판정한다."""
    start = max(first[0].t_s, second[0].t_s)
    end = min(first[-1].t_s, second[-1].t_s)
    if end < start:
        return False
    samples = max(1, int(math.ceil((end - start) / step_s)))
    for index in range(samples + 1):
        t_s = start + (end - start) * index / samples
        first_x, first_y = _position_at(first, t_s)
        second_x, second_y = _position_at(second, t_s)
        if math.hypot(first_x - second_x, first_y - second_y) <= radius_m:
            return True
    return False


__all__ = [
    "AssignedPathRequest",
    "ClearanceDecision",
    "CommandAcceptance",
    "ItineraryPoint",
    "PathExecutionResult",
    "PathScheduleCoordinator",
    "PlannedNavPath",
    "ReplanTicket",
    "ScheduleRegistration",
    "validate_assigned_command",
]
