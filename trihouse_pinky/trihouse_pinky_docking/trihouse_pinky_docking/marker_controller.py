"""ArUco를 정면으로 맞춘 뒤 180도 돌아 협로에 후진하는 순수 제어기.

ROS 메시지와 타이머는 ``dock_node``가 담당한다. 이 모듈은 센서 표본과 pose를
받아 속도 명령만 결정하므로 실물과 같은 상태 전이를 단위 테스트할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, hypot, pi, sin, cos


IDLE = "idle"
SEARCHING = "searching"
ALIGNING = "aligning"
TURNING = "turning"
REVERSING = "reversing"
COMPLETE = "complete"
FAILED = "failed"


def normalize(angle: float) -> float:
    return atan2(sin(angle), cos(angle))


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


@dataclass(frozen=True)
class DockCommand:
    linear_x: float = 0.0
    angular_z: float = 0.0


@dataclass(frozen=True)
class MarkerSample:
    marker_id: str
    # TTL은 수신 노드의 시간축에서 판단한다. camera/bridge와 로봇의 시계가 달라도
    # 과거 또는 미래 표본으로 오인해 움직임을 막거나 허용하지 않기 위해서다.
    received_at_s: float
    ttl_s: float
    confidence: float
    forward_m: float
    left_m: float


@dataclass(frozen=True)
class DockProfile:
    marker_id: str
    minimum_confidence: float
    stable_observations: int
    observation_timeout_s: float
    standoff_m: float
    distance_tolerance_m: float
    bearing_tolerance_rad: float
    turn_direction: int
    reverse_distance_m: float
    max_linear_mps: float = 0.04
    max_angular_rps: float = 0.30
    yaw_tolerance_rad: float = 0.04
    reverse_position_tolerance_m: float = 0.015
    phase_timeout_s: float = 30.0
    activation_x_m: float | None = None
    activation_y_m: float | None = None
    activation_radius_m: float | None = None

    def __post_init__(self) -> None:
        if self.turn_direction not in (-1, 1):
            raise ValueError("turn_direction은 -1 또는 1이어야 한다")
        if self.stable_observations < 1:
            raise ValueError("stable_observations는 1 이상이어야 한다")
        if self.reverse_distance_m <= 0.0:
            raise ValueError("reverse_distance_m은 양수여야 한다")

    def allows_activation(self, map_x_m: float, map_y_m: float) -> bool:
        """실측한 회전 준비 공간에서만 도킹 상태기를 시작한다."""
        if (
            self.activation_x_m is None
            or self.activation_y_m is None
            or self.activation_radius_m is None
        ):
            return False
        return hypot(
            map_x_m - self.activation_x_m,
            map_y_m - self.activation_y_m,
        ) <= self.activation_radius_m


class MarkerDockController:
    """탐색→정렬→반 바퀴 회전→방향 유지 후진 상태 머신."""

    def __init__(self, profile: DockProfile) -> None:
        self.profile = profile
        self.state = IDLE
        self.failure: str | None = None
        self._observation: MarkerSample | None = None
        self._consecutive = 0
        self._phase_started_s = 0.0
        self._turn_target_yaw: float | None = None
        self._reverse_origin: tuple[float, float] | None = None

    @property
    def is_failed(self) -> bool:
        return self.state == FAILED

    @property
    def is_complete(self) -> bool:
        return self.state == COMPLETE

    def begin(self, *, now_s: float, pose: tuple[float, float, float]) -> None:
        del pose
        self.state = SEARCHING
        self.failure = None
        self._observation = None
        self._consecutive = 0
        self._phase_started_s = now_s
        self._turn_target_yaw = None
        self._reverse_origin = None

    def observe(self, sample: MarkerSample, *, now_s: float) -> None:
        valid = (
            sample.marker_id == self.profile.marker_id
            and sample.confidence >= self.profile.minimum_confidence
            and sample.ttl_s > 0.0
            and 0.0 <= now_s - sample.received_at_s
            <= min(sample.ttl_s, self.profile.observation_timeout_s)
        )
        if not valid:
            self._observation = None
            self._consecutive = 0
            return
        self._observation = sample
        self._consecutive += 1
        if self.state == SEARCHING and self._consecutive >= self.profile.stable_observations:
            self.state = ALIGNING
            self._phase_started_s = now_s

    def _fail(self, reason: str) -> DockCommand:
        self.failure = reason
        self.state = FAILED
        return DockCommand()

    def abort(self, reason: str) -> DockCommand:
        """외부 센서·취소·안전 계층 실패를 정지 상태로 고정한다."""
        return self._fail(reason)

    def advance(
        self,
        *,
        now_s: float,
        pose: tuple[float, float, float],
        vision_ready: bool,
    ) -> DockCommand:
        if self.state in (IDLE, COMPLETE, FAILED):
            return DockCommand()
        if now_s - self._phase_started_s > self.profile.phase_timeout_s:
            return self._fail(f"{self.state}_timeout")

        if self.state in (SEARCHING, ALIGNING):
            if not vision_ready:
                return self._fail("vision_not_ready")
            observation = self._observation
            if observation is None:
                return DockCommand()
            age = now_s - observation.received_at_s
            if age < 0.0 or age > min(
                observation.ttl_s, self.profile.observation_timeout_s
            ):
                self._observation = None
                self._consecutive = 0
                self.state = SEARCHING
                return DockCommand()
            if self.state == SEARCHING:
                return DockCommand()

            bearing = atan2(observation.left_m, observation.forward_m)
            distance_error = observation.forward_m - self.profile.standoff_m
            if abs(bearing) > self.profile.bearing_tolerance_rad:
                return DockCommand(
                    angular_z=_clamp(1.5 * bearing, self.profile.max_angular_rps)
                )
            if abs(distance_error) > self.profile.distance_tolerance_m:
                return DockCommand(
                    linear_x=_clamp(0.5 * distance_error, self.profile.max_linear_mps),
                    angular_z=_clamp(0.8 * bearing, self.profile.max_angular_rps),
                )

            self.state = TURNING
            self._phase_started_s = now_s
            self._turn_target_yaw = normalize(
                pose[2] + self.profile.turn_direction * pi
            )
            return DockCommand()

        if self.state == TURNING:
            assert self._turn_target_yaw is not None
            error = normalize(self._turn_target_yaw - pose[2])
            if abs(error) <= self.profile.yaw_tolerance_rad:
                self.state = REVERSING
                self._phase_started_s = now_s
                self._reverse_origin = (pose[0], pose[1])
                return DockCommand()
            speed = _clamp(1.2 * error, self.profile.max_angular_rps)
            # turn_direction은 정확히 pi 떨어진 두 회전 방향 중 벽에서 먼 쪽을 고른다.
            if abs(abs(error) - pi) <= 1e-6:
                speed = self.profile.turn_direction * self.profile.max_angular_rps
            return DockCommand(angular_z=speed)

        assert self.state == REVERSING and self._reverse_origin is not None
        travelled = hypot(
            pose[0] - self._reverse_origin[0], pose[1] - self._reverse_origin[1]
        )
        remaining = self.profile.reverse_distance_m - travelled
        if remaining <= self.profile.reverse_position_tolerance_m:
            self.state = COMPLETE
            return DockCommand()
        assert self._turn_target_yaw is not None
        yaw_error = normalize(self._turn_target_yaw - pose[2])
        linear = -min(self.profile.max_linear_mps, max(0.015, 0.5 * remaining))
        angular = _clamp(1.2 * yaw_error, self.profile.max_angular_rps)
        return DockCommand(linear_x=linear, angular_z=angular)


__all__ = [
    "ALIGNING", "COMPLETE", "FAILED", "IDLE", "REVERSING", "SEARCHING",
    "TURNING", "DockCommand", "DockProfile", "MarkerDockController",
    "MarkerSample", "normalize",
]
