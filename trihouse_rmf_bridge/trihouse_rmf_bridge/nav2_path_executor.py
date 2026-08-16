"""배정된 Pinky의 Nav2 후보 경로 계산과 RMF 승인 후 추종.

P0 이동은 `NavigateToPose` 한 번으로 끝나지 않는다. 먼저
`ComputePathToPose`로 실제 경로를 계산하고(이 호출은 로봇을 움직이지
않는다), 그 경로를 배정된 RMF participant itinerary로 등록하고, 충돌이
해소된 뒤에야 `FollowPath`를 호출한다. Nav2가 재계획을 요구하거나 실행
중인 경로가 등록본과 다르면 즉시 취소·보류하고 override handle을 반납한 뒤
다시 계산·등록한다.

Nav2 action은 Protocol로 주입해 이 모듈이 rclpy 없이도 검증되도록 한다.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Callable, Iterable, Protocol, Sequence

from control_tower.rmf_adapter.path_schedule import (
    AssignedPathRequest,
    PathExecutionResult,
    PlannedNavPath,
    validate_assigned_command,
)


class AssignmentMismatch(RuntimeError):
    """다른 Pinky에게 배정된 명령이 이 adapter에 도착했다."""


class Nav2PathUnavailable(RuntimeError):
    """Nav2 planner가 없거나 유효한 후보 경로를 돌려주지 않았다."""


class FollowOutcome(Enum):
    SUCCEEDED = "SUCCEEDED"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"
    ABORTED = "ABORTED"
    CANCELLED = "CANCELLED"


_FOLLOW_REASONS = {
    FollowOutcome.REPLAN_REQUIRED: "NAV2_REPLAN_REQUIRED",
    FollowOutcome.ABORTED: "NAV2_FOLLOW_ABORTED",
    FollowOutcome.CANCELLED: "NAV2_FOLLOW_CANCELLED",
}


class ComputePathClient(Protocol):
    def server_is_ready(self) -> bool: ...

    def compute_path_to_pose(
        self,
        *,
        goal_pose: tuple[float, float, float],
        map_revision: str,
        exclude_zones: Iterable[tuple[float, float, float]] = (),
    ) -> tuple[Sequence[tuple[float, float, float]], float] | None: ...


class FollowPathClient(Protocol):
    def server_is_ready(self) -> bool: ...

    def follow_path(
        self, poses: Sequence[tuple[float, float, float]]
    ) -> FollowOutcome: ...

    def cancel(self) -> None: ...


class SchedulePort(Protocol):
    """`PathScheduleCoordinator`가 만족하는 최소 계약."""

    def register(self, path: PlannedNavPath, *, start_time_s: float): ...

    def clearance(self, robot_name: str): ...

    def verify_execution(self, robot_name: str, *, path_hash: str): ...

    def hold_for_replan(self, robot_name: str, *, reason_code: str): ...

    def release(self, robot_name: str) -> None: ...

    def release_override(self, robot_name: str) -> None: ...


class Nav2PathExecutor:
    """한 Pinky namespace의 Nav2 경로 계산·등록·추종을 담당한다."""

    def __init__(
        self,
        *,
        robot_name: str,
        compute_client: ComputePathClient,
        follow_client: FollowPathClient,
        schedule: SchedulePort,
        clock: Callable[[], float],
    ) -> None:
        if not robot_name.strip():
            raise ValueError("robot_name is required")
        self._robot_name = robot_name.strip()
        self._compute = compute_client
        self._follow = follow_client
        self._schedule = schedule
        self._clock = clock

    @property
    def robot_name(self) -> str:
        return self._robot_name

    def compute(
        self,
        request: AssignedPathRequest,
        *,
        exclude_zones: Iterable[tuple[float, float, float]] = (),
    ) -> PlannedNavPath:
        """Nav2로 후보 경로만 계산한다. 이 호출은 로봇을 움직이지 않는다."""
        acceptance = validate_assigned_command(
            adapter_robot_name=self._robot_name, request=request
        )
        if not acceptance.accepted:
            raise AssignmentMismatch(
                f"{acceptance.reason_code}: {self._robot_name} "
                f"cannot execute work assigned to {request.robot_name}"
            )
        if not self._compute.server_is_ready():
            raise Nav2PathUnavailable("Nav2 ComputePathToPose server is not available")
        computed = self._compute.compute_path_to_pose(
            goal_pose=request.goal_pose,
            map_revision=request.map_revision,
            exclude_zones=tuple(exclude_zones),
        )
        if not computed:
            raise Nav2PathUnavailable("Nav2 returned no candidate path")
        poses, travel_time_s = computed
        frozen = tuple(
            (float(pose[0]), float(pose[1]), float(pose[2])) for pose in poses
        )
        return PlannedNavPath(
            request=request,
            poses=frozen,
            travel_time_s=float(travel_time_s),
            path_hash=path_hash(request.map_revision, frozen),
        )

    def follow(
        self, path: PlannedNavPath, *, register: bool = True
    ) -> PathExecutionResult:
        """일정 등록·승인 확인 뒤에만 `FollowPath`를 호출한다."""
        acceptance = validate_assigned_command(
            adapter_robot_name=self._robot_name, request=path.request
        )
        if not acceptance.accepted:
            raise AssignmentMismatch(
                f"{acceptance.reason_code}: {self._robot_name} "
                f"cannot execute work assigned to {path.request.robot_name}"
            )

        if register:
            self._schedule.register(path, start_time_s=self._clock())

        verified = self._schedule.verify_execution(
            self._robot_name, path_hash=path.path_hash
        )
        if not verified.cleared:
            self._follow.cancel()
            return self._hold(path, verified.reason_code)

        clearance = self._schedule.clearance(self._robot_name)
        if not clearance.cleared:
            # 승인 전에는 어떤 모터 명령도 나가지 않는다.
            return PathExecutionResult(
                reached=False,
                reason_code=clearance.reason_code,
                path_hash=path.path_hash,
            )

        if not self._follow.server_is_ready():
            self._schedule.release(self._robot_name)
            self._schedule.release_override(self._robot_name)
            return PathExecutionResult(
                reached=False,
                reason_code="NAV2_FOLLOW_UNAVAILABLE",
                path_hash=path.path_hash,
            )

        outcome = self._follow.follow_path(path.poses)
        if outcome is FollowOutcome.SUCCEEDED:
            self._schedule.release(self._robot_name)
            self._schedule.release_override(self._robot_name)
            return PathExecutionResult(
                reached=True, reason_code="REACHED", path_hash=path.path_hash
            )

        reason = _FOLLOW_REASONS.get(outcome, "NAV2_FOLLOW_FAILED")
        self._follow.cancel()
        return self._hold(path, reason)

    def _hold(self, path: PlannedNavPath, reason_code: str) -> PathExecutionResult:
        """경로와 override handle을 모두 반납하고 재계산을 기다린다."""
        self._schedule.hold_for_replan(self._robot_name, reason_code=reason_code)
        return PathExecutionResult(
            reached=False, reason_code=reason_code, path_hash=path.path_hash
        )


def path_hash(
    map_revision: str, poses: Sequence[tuple[float, float, float]]
) -> str:
    """같은 지도·같은 pose 열이면 항상 같은 해시를 만든다."""
    digest = hashlib.sha256()
    digest.update(map_revision.encode("utf-8"))
    for x, y, yaw in poses:
        digest.update(f"|{x:.6f},{y:.6f},{yaw:.6f}".encode("ascii"))
    return digest.hexdigest()


__all__ = [
    "AssignmentMismatch",
    "ComputePathClient",
    "FollowOutcome",
    "FollowPathClient",
    "Nav2PathExecutor",
    "Nav2PathUnavailable",
    "SchedulePort",
    "path_hash",
]
