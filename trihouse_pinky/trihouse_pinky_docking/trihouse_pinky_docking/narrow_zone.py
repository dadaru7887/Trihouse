"""창고 협로의 설정, 기하, 결정론적 속도 제어를 한 곳에서 소유한다.

이 모듈은 ROS를 import하지 않는다. Fleet/도킹 노드는 여기서 나온 속도 명령을
`cmd_vel_dock`으로 전달하고, 실제 모터 입력은 safety supervisor가 단독 소유한다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import atan2, cos, hypot, isfinite, sin
from typing import Any, Mapping, Sequence


ENTER = "enter"
EXIT = "exit"
ROTATE = "rotate"
STRAIGHT = "straight"
EXIT_ZONE = "exit_zone"
STEP_KINDS = (ROTATE, STRAIGHT, EXIT_ZONE)


class NarrowZoneConfigError(ValueError):
    """협로 profile 문서 자체를 신뢰할 수 없다."""


@dataclass(frozen=True)
class Pose2D:
    x: float
    y: float
    yaw: float


@dataclass(frozen=True)
class OrientedZone:
    x: float
    y: float
    yaw: float
    length: float
    width: float

    def contains(self, pose_or_x: Pose2D | float, y: float | None = None) -> bool:
        if isinstance(pose_or_x, Pose2D):
            x_value, y_value = pose_or_x.x, pose_or_x.y
        else:
            if y is None:
                raise TypeError("x를 전달하면 y도 필요하다")
            x_value, y_value = float(pose_or_x), float(y)
        dx, dy = x_value - self.x, y_value - self.y
        c, s = cos(-self.yaw), sin(-self.yaw)
        along = dx * c - dy * s
        across = dx * s + dy * c
        return abs(along) <= self.length / 2 and abs(across) <= self.width / 2


@dataclass(frozen=True)
class CircularTrigger:
    """대기/충전 waypoint 주변에서 공통 탈출 규칙을 시작하는 원형 경계."""

    x: float
    y: float
    radius: float

    def contains(self, pose: Pose2D) -> bool:
        return hypot(pose.x - self.x, pose.y - self.y) <= self.radius


@dataclass(frozen=True)
class MotionStep:
    kind: str
    value: float | None

    def __post_init__(self) -> None:
        if self.kind not in STEP_KINDS:
            raise NarrowZoneConfigError(f"알 수 없는 협로 단계 {self.kind!r}")
        if self.kind == EXIT_ZONE:
            if self.value is not None:
                object.__setattr__(self, "value", None)
        elif not isinstance(self.value, (int, float)):
            raise NarrowZoneConfigError(f"{self.kind} 단계에는 숫자가 필요하다")


@dataclass(frozen=True)
class MeasurementState:
    entry_pose: bool = False
    dock_pose: bool = False
    enter: bool = False
    exit: bool = False

    @property
    def complete(self) -> bool:
        return self.entry_pose and self.dock_pose and self.enter and self.exit


@dataclass(frozen=True)
class EntryPassageConfig:
    """출입구 밖 정렬부터 내부 도크 접근까지의 기하와 제한값."""

    doorway: Pose2D
    inside_turn: Pose2D
    dock_yaw: float
    entry_yaw_tolerance_rad: float
    entry_straight_speed_mps: float
    heading_correction_max_rps: float
    recovery_distance_m: float
    recovery_speed_mps: float
    recovery_max_attempts: int
    recovery_timeout_s: float


@dataclass(frozen=True)
class NarrowZoneProfile:
    destination_code: str
    enabled: bool
    approach_required: bool
    entry_pose: Pose2D | None
    entry_zone: OrientedZone | None
    zone: OrientedZone | None
    enter: tuple[MotionStep, ...]
    exit: tuple[MotionStep, ...]
    dock_target: Pose2D | None
    exit_target: Pose2D | None
    measurement: MeasurementState
    marker_id: str | None = None
    metadata: Mapping[str, Any] | None = None
    issues: tuple[str, ...] = ()
    departure_triggers: tuple[CircularTrigger, ...] = ()
    exit_completion_radius_m: float | None = None
    entry_passage: EntryPassageConfig | None = None

    @property
    def readiness_code(self) -> str:
        if not self.enabled:
            return "NARROW_PROFILE_DISABLED"
        if (
            self.entry_pose is None
            or self.zone is None
            or not self.enter
            or not self.exit
            or self.dock_target is None
            or self.exit_target is None
            or self.issues
        ):
            return "NARROW_PROFILE_INCOMPLETE"
        if not self.measurement.complete:
            return "NARROW_PROFILE_UNMEASURED"
        return "READY"

    @property
    def executable(self) -> bool:
        return self.readiness_code == "READY"

    def direction_readiness_code(self, direction: str) -> str:
        """진입 전용/탈출 전용 profile을 구분해 한 방향의 운영 준비도를 판정한다."""
        if not self.enabled:
            return "NARROW_PROFILE_DISABLED"
        if direction == ENTER:
            if not self.approach_required:
                return "READY"
            # 창고 배정은 진입만 성공하고 탈출할 수 없는 상태를 허용하지 않는다.
            return self.readiness_code
        if direction == EXIT:
            if (
                (self.zone is None and not self.departure_triggers)
                or not self.exit
                or self.exit_target is None
                or self.issues
            ):
                return "NARROW_PROFILE_INCOMPLETE"
            if not self.measurement.exit:
                return "NARROW_PROFILE_UNMEASURED"
            return "READY"
        raise ValueError(f"direction은 {ENTER!r} 또는 {EXIT!r}이어야 한다")

    def calibration_ready(self, direction: str) -> bool:
        """사람이 지켜보는 1회 보정 주행에 필요한 구조 값만 있는가.

        운영 배정의 `executable`과 의도적으로 다르다. 아직 실측되지 않은 시퀀스를
        검증하려면 후보 값으로 한 번은 움직여야 하지만, 그 상태가 일반 주문에 열리면
        안 된다. disabled profile은 보정도 명시적으로 켜기 전까지 거절한다.
        """
        if not self.enabled or (self.zone is None and not self.departure_triggers):
            return False
        if direction == ENTER:
            return bool(
                self.entry_pose
                and (self.entry_passage is not None or self.enter)
                and self.dock_target
            )
        if direction == EXIT:
            return bool(self.exit and self.exit_target)
        raise ValueError(f"direction은 {ENTER!r} 또는 {EXIT!r}이어야 한다")

    def with_measurement(self, **changes: bool) -> "NarrowZoneProfile":
        """테스트/검증 단계에서 measurement 상태만 명시적으로 바꾼 복사본."""
        return replace(self, measurement=replace(self.measurement, **changes))

    @property
    def readiness_reason(self) -> str:
        reasons = {
            "READY": "실행 가능",
            "NARROW_PROFILE_DISABLED": "협로 profile이 비활성화되어 있다",
            "NARROW_PROFILE_INCOMPLETE": "협로 profile 필수 값이 온전하지 않다",
            "NARROW_PROFILE_UNMEASURED": "협로 진입·도크·진입·탈출 실측이 완료되지 않았다",
        }
        return reasons[self.readiness_code]


@dataclass(frozen=True)
class MotionLimits:
    max_linear_mps: float = 0.06
    max_angular_rps: float = 0.5
    linear_tolerance_m: float = 0.02
    angular_tolerance_rad: float = 0.05
    step_timeout_s: float = 25.0


@dataclass(frozen=True)
class VelocityCommand:
    linear_x: float = 0.0
    angular_z: float = 0.0

    @property
    def is_zero(self) -> bool:
        return self.linear_x == 0.0 and self.angular_z == 0.0


@dataclass(frozen=True)
class SafetyObservation:
    stopped: bool = False
    emergency: bool = False
    detail: str = "clear"


def normalize(angle: float) -> float:
    return atan2(sin(angle), cos(angle))


class EntryPoseController:
    """Nav2 handoff 위치에서 실측 entry pose까지 저속으로 정렬한다.

    EN: The entry zone is only a control handoff boundary. This controller
    closes the remaining position and yaw error before measured dock steps run.
    KO: entry zone은 제어권 인계 경계일 뿐이다. 실측 도킹 스텝을 실행하기 전에
    남은 위치와 yaw 오차를 이 제어기가 닫는다.
    """

    FACE_ENTRY = "face_entry"
    DRIVE_ENTRY = "drive_entry"
    MATCH_YAW = "match_yaw"
    COMPLETE = "complete"

    def __init__(
        self, target: Pose2D | None, *, limits: MotionLimits | None = None
    ) -> None:
        self.target = target
        self.limits = limits or MotionLimits()
        self.phase = self.FACE_ENTRY
        self.failure: str | None = None
        self._started = False
        self._last_progress_s = 0.0
        self._best_error: float | None = None

    @property
    def is_complete(self) -> bool:
        return self._started and self.failure is None and self.phase == self.COMPLETE

    @property
    def progress(self) -> str:
        return self.phase

    def begin(self, pose: Pose2D, *, now_s: float) -> bool:
        if self.target is None:
            self.failure = "entry_pose_missing"
            return False
        self._started = True
        self._last_progress_s = now_s
        self._best_error = None
        if hypot(self.target.x - pose.x, self.target.y - pose.y) <= self.limits.linear_tolerance_m:
            self.phase = self.MATCH_YAW
        return True

    def cancel(self, reason: str = "canceled") -> None:
        if not self.is_complete:
            self.failure = reason

    def advance(self, pose: Pose2D, *, now_s: float) -> VelocityCommand:
        if not self._started or self.failure is not None or self.is_complete:
            return VelocityCommand()
        assert self.target is not None

        dx = self.target.x - pose.x
        dy = self.target.y - pose.y
        distance = hypot(dx, dy)
        if self.phase == self.FACE_ENTRY:
            if distance <= self.limits.linear_tolerance_m:
                self._transition(self.MATCH_YAW, now_s)
                return VelocityCommand()
            error = normalize(atan2(dy, dx) - pose.yaw)
            if abs(error) <= self.limits.angular_tolerance_rad:
                self._transition(self.DRIVE_ENTRY, now_s)
                return self.advance(pose, now_s=now_s)
            if self._timed_out(abs(error), self.limits.angular_tolerance_rad, now_s):
                return VelocityCommand()
            return VelocityCommand(angular_z=self._angular_speed(error))

        if self.phase == self.DRIVE_ENTRY:
            if distance <= self.limits.linear_tolerance_m:
                self._transition(self.MATCH_YAW, now_s)
                return self.advance(pose, now_s=now_s)
            heading_error = normalize(atan2(dy, dx) - pose.yaw)
            if abs(heading_error) > self.limits.angular_tolerance_rad:
                self._transition(self.FACE_ENTRY, now_s)
                return VelocityCommand()
            if self._timed_out(distance, self.limits.linear_tolerance_m, now_s):
                return VelocityCommand()
            speed = min(self.limits.max_linear_mps, 0.6 * distance)
            return VelocityCommand(linear_x=speed)

        yaw_error = normalize(self.target.yaw - pose.yaw)
        if abs(yaw_error) <= self.limits.angular_tolerance_rad:
            self.phase = self.COMPLETE
            return VelocityCommand()
        if self._timed_out(abs(yaw_error), self.limits.angular_tolerance_rad, now_s):
            return VelocityCommand()
        return VelocityCommand(angular_z=self._angular_speed(yaw_error))

    def _transition(self, phase: str, now_s: float) -> None:
        self.phase = phase
        self._last_progress_s = now_s
        self._best_error = None

    def _timed_out(self, error: float, threshold: float, now_s: float) -> bool:
        if self._best_error is None or error <= self._best_error - threshold:
            self._best_error = error
            self._last_progress_s = now_s
        if now_s - self._last_progress_s <= self.limits.step_timeout_s:
            return False
        self.failure = "entry_alignment_timeout"
        return True

    def _angular_speed(self, error: float) -> float:
        return max(
            -self.limits.max_angular_rps,
            min(self.limits.max_angular_rps, 1.2 * error),
        )


class WarehouseEntryController:
    """넓은 구역에서 정렬한 뒤 출입구를 직선 통과하고 내부에서 회전한다."""

    ENTRY_ALIGNMENT = "entry_alignment"
    ENTER_STRAIGHT = "enter_straight"
    INSIDE_CLEAR = "inside_clear"
    TURN_TO_DOCK = "turn_to_dock"
    DOCK_APPROACH = "dock_approach"
    RECOVER_ROTATION_SPACE = "recover_rotation_space"
    COMPLETE = "complete"
    FAILED = "failed"

    def __init__(
        self,
        profile: NarrowZoneProfile,
        *,
        limits: MotionLimits | None = None,
        calibration: bool = False,
    ) -> None:
        self.profile = profile
        self.config = profile.entry_passage
        self.limits = limits or MotionLimits()
        self.calibration = calibration
        self.phase = self.ENTRY_ALIGNMENT
        self.failure: str | None = None
        self._started = False
        self._last_progress_s = 0.0
        self._best_error: float | None = None
        self.recovery_attempt = 0
        self._recovery_origin: Pose2D | None = None
        self._recovery_started_s = 0.0

    @property
    def is_complete(self) -> bool:
        return self._started and self.failure is None and self.phase == self.COMPLETE

    @property
    def progress(self) -> str:
        return self.phase

    def begin(self, pose: Pose2D, *, now_s: float) -> bool:
        if self.config is None or self.profile.dock_target is None:
            self.failure = "entry_passage_missing"
            self.phase = self.FAILED
            return False
        readiness = self.profile.direction_readiness_code(ENTER)
        if readiness != "READY" and not (
            self.calibration and self.profile.calibration_ready(ENTER)
        ):
            self.failure = readiness
            self.phase = self.FAILED
            return False
        self._started = True
        self._last_progress_s = now_s
        yaw_error = abs(normalize(self.config.doorway.yaw - pose.yaw))
        if yaw_error <= self.config.entry_yaw_tolerance_rad:
            self.phase = self.ENTER_STRAIGHT
            self._best_error = hypot(
                self.config.inside_turn.x - pose.x,
                self.config.inside_turn.y - pose.y,
            )
        else:
            self._best_error = yaw_error
        return True

    def cancel(self, reason: str = "canceled") -> None:
        if not self.is_complete:
            self.failure = reason
            self.phase = self.FAILED

    def advance(
        self,
        pose: Pose2D,
        *,
        now_s: float,
        safety: SafetyObservation = SafetyObservation(),
    ) -> VelocityCommand:
        if not self._started or self.failure is not None or self.is_complete:
            return VelocityCommand()
        assert self.config is not None
        assert self.profile.dock_target is not None

        if safety.emergency:
            return self._fail("safety_emergency")
        if safety.stopped:
            if (
                safety.detail == "swept_stop"
                and self.phase == self.RECOVER_ROTATION_SPACE
            ):
                if now_s - self._recovery_started_s > self.config.recovery_timeout_s:
                    return self._fail("swept_recovery_timeout")
                return VelocityCommand()
            if safety.detail == "swept_stop" and self.phase == self.ENTRY_ALIGNMENT:
                if self.recovery_attempt >= self.config.recovery_max_attempts:
                    return self._fail("swept_recovery_exhausted")
                self.recovery_attempt += 1
                self.phase = self.RECOVER_ROTATION_SPACE
                self._recovery_origin = pose
                self._recovery_started_s = now_s
                return VelocityCommand()
            return self._fail(f"safety_stop:{safety.detail or 'unknown'}")

        if self.phase == self.RECOVER_ROTATION_SPACE:
            assert self._recovery_origin is not None
            if now_s - self._recovery_started_s > self.config.recovery_timeout_s:
                return self._fail("swept_recovery_timeout")
            travelled = hypot(
                pose.x - self._recovery_origin.x,
                pose.y - self._recovery_origin.y,
            )
            if travelled >= self.config.recovery_distance_m:
                self._transition(self.ENTRY_ALIGNMENT, now_s)
                self._best_error = abs(
                    normalize(self.config.doorway.yaw - pose.yaw)
                )
                return VelocityCommand()
            return VelocityCommand(linear_x=-self.config.recovery_speed_mps)

        if self.phase == self.ENTRY_ALIGNMENT:
            error = normalize(self.config.doorway.yaw - pose.yaw)
            if abs(error) <= self.config.entry_yaw_tolerance_rad:
                self._transition(self.ENTER_STRAIGHT, now_s)
                return self.advance(pose, now_s=now_s)
            if self._timed_out(
                abs(error), self.config.entry_yaw_tolerance_rad, now_s,
                "entry_alignment_timeout",
            ):
                return VelocityCommand()
            return VelocityCommand(angular_z=self._angular_speed(error))

        if self.phase == self.ENTER_STRAIGHT:
            distance = hypot(
                self.config.inside_turn.x - pose.x,
                self.config.inside_turn.y - pose.y,
            )
            if distance <= self.limits.linear_tolerance_m:
                self._transition(self.INSIDE_CLEAR, now_s)
                return VelocityCommand()
            if self._timed_out(
                distance, self.limits.linear_tolerance_m, now_s,
                "entry_straight_timeout",
            ):
                return VelocityCommand()
            heading_error = normalize(self.config.doorway.yaw - pose.yaw)
            correction = max(
                -self.config.heading_correction_max_rps,
                min(self.config.heading_correction_max_rps, 1.2 * heading_error),
            )
            speed = min(
                self.config.entry_straight_speed_mps,
                max(0.02, 0.6 * distance),
            )
            return VelocityCommand(linear_x=speed, angular_z=correction)

        if self.phase == self.INSIDE_CLEAR:
            self._transition(self.TURN_TO_DOCK, now_s)
            return VelocityCommand()

        if self.phase == self.TURN_TO_DOCK:
            error = normalize(self.config.dock_yaw - pose.yaw)
            if abs(error) <= self.limits.angular_tolerance_rad:
                self._transition(self.DOCK_APPROACH, now_s)
                return VelocityCommand()
            if self._timed_out(
                abs(error), self.limits.angular_tolerance_rad, now_s,
                "inside_turn_timeout",
            ):
                return VelocityCommand()
            return VelocityCommand(angular_z=self._angular_speed(error))

        if self.phase == self.DOCK_APPROACH:
            target = self.profile.dock_target
            dx, dy = target.x - pose.x, target.y - pose.y
            distance = hypot(dx, dy)
            yaw_error = normalize(self.config.dock_yaw - pose.yaw)
            if (
                distance <= self.limits.linear_tolerance_m
                and abs(yaw_error) <= self.limits.angular_tolerance_rad
            ):
                self.phase = self.COMPLETE
                return VelocityCommand()
            error = max(distance, abs(yaw_error))
            if self._timed_out(
                error,
                min(self.limits.linear_tolerance_m, self.limits.angular_tolerance_rad),
                now_s,
                "dock_approach_timeout",
            ):
                return VelocityCommand()
            forward = dx * cos(pose.yaw) + dy * sin(pose.yaw)
            sign = 1.0 if forward >= 0.0 else -1.0
            speed = min(self.limits.max_linear_mps, max(0.02, 0.6 * distance))
            return VelocityCommand(
                linear_x=sign * speed,
                angular_z=self._angular_speed(yaw_error),
            )

        return VelocityCommand()

    def _transition(self, phase: str, now_s: float) -> None:
        self.phase = phase
        self._last_progress_s = now_s
        self._best_error = None

    def _fail(self, reason: str) -> VelocityCommand:
        self.failure = reason
        self.phase = self.FAILED
        return VelocityCommand()

    def _timed_out(
        self,
        error: float,
        threshold: float,
        now_s: float,
        reason: str,
    ) -> bool:
        if self._best_error is None or error <= self._best_error - threshold:
            self._best_error = error
            self._last_progress_s = now_s
        if now_s - self._last_progress_s <= self.limits.step_timeout_s:
            return False
        self.failure = reason
        self.phase = self.FAILED
        return True

    def _angular_speed(self, error: float) -> float:
        return max(
            -self.limits.max_angular_rps,
            min(self.limits.max_angular_rps, 1.2 * error),
        )


class NarrowZoneController:
    """pose 되먹임으로 한 번의 창고 진입 또는 탈출을 실행한다."""

    def __init__(
        self,
        profile: NarrowZoneProfile,
        *,
        direction: str,
        limits: MotionLimits | None = None,
        calibration: bool = False,
    ) -> None:
        if direction not in (ENTER, EXIT):
            raise ValueError(f"direction은 {ENTER!r} 또는 {EXIT!r}이어야 한다")
        self.profile = profile
        self.direction = direction
        self.limits = limits or MotionLimits()
        self.calibration = calibration
        self.steps = profile.enter if direction == ENTER else profile.exit
        self.step_index = 0
        self.failure: str | None = None
        self._started = False
        self._origin: Pose2D | None = None
        self._step_started_s = 0.0
        self._last_progress_s = 0.0
        self._best_progress = 0.0

    @classmethod
    def for_steps(
        cls,
        profile: NarrowZoneProfile,
        *,
        direction: str,
        steps: Sequence[MotionStep | tuple[str, float | None]],
        limits: MotionLimits | None = None,
    ) -> "NarrowZoneController":
        parsed = tuple(
            step if isinstance(step, MotionStep) else MotionStep(step[0], step[1])
            for step in steps
        )
        temporary = replace(
            profile,
            enter=parsed if direction == ENTER else profile.enter,
            exit=parsed if direction == EXIT else profile.exit,
        )
        return cls(temporary, direction=direction, limits=limits)

    @property
    def is_complete(self) -> bool:
        return self._started and self.failure is None and self.step_index >= len(self.steps)

    @property
    def progress(self) -> str:
        return f"{min(self.step_index + 1, len(self.steps))}/{len(self.steps)}"

    def begin(self, pose: Pose2D, *, now_s: float) -> bool:
        readiness = self.profile.direction_readiness_code(self.direction)
        if readiness != "READY" and not (
            self.calibration and self.profile.calibration_ready(self.direction)
        ):
            self.failure = readiness
            return False
        if not self.steps:
            self.failure = "empty_sequence"
            return False
        self._started = True
        self._origin = pose
        self._step_started_s = now_s
        self._last_progress_s = now_s
        self._best_progress = 0.0
        return True

    def cancel(self, reason: str = "canceled") -> None:
        if not self.is_complete:
            self.failure = reason

    def advance(self, pose: Pose2D, *, now_s: float) -> VelocityCommand:
        if not self._started or self.failure is not None or self.is_complete:
            return VelocityCommand()
        if (
            self.direction == EXIT
            and self.profile.exit_target is not None
            and self.profile.exit_completion_radius_m is not None
            and hypot(
                pose.x - self.profile.exit_target.x,
                pose.y - self.profile.exit_target.y,
            ) <= self.profile.exit_completion_radius_m
        ):
            # 충전 협로는 고정 거리의 끝보다 실측 탈출점 도달이 더 강한 완료 조건이다.
            self.step_index = len(self.steps)
            return VelocityCommand()
        step = self.steps[self.step_index]
        progress, threshold = self._step_progress(step, pose)
        # EN: This is a no-progress watchdog, not a total step deadline. Safety
        # stops may lengthen a narrow traversal while the robot still advances.
        # KO: 이 timeout은 스텝 총시간이 아니라 무진전 감시다. 안전 정지가
        # 반복되어도 로봇이 실제로 전진하면 협로 동작을 계속한다.
        if progress >= self._best_progress + threshold:
            self._best_progress = progress
            self._last_progress_s = now_s
        if now_s - self._last_progress_s > self.limits.step_timeout_s:
            self.failure = "step_timeout"
            return VelocityCommand()

        if step.kind == ROTATE:
            command, done = self._rotate(pose, float(step.value))
        elif step.kind == STRAIGHT:
            command, done = self._straight(pose, float(step.value))
        else:
            command, done = self._exit_zone(pose)

        if not done:
            return command
        self.step_index += 1
        self._origin = pose
        self._step_started_s = now_s
        self._last_progress_s = now_s
        self._best_progress = 0.0
        return VelocityCommand()

    def _step_progress(self, step: MotionStep, pose: Pose2D) -> tuple[float, float]:
        assert self._origin is not None
        if step.kind == ROTATE:
            initial_error = abs(normalize(float(step.value) - self._origin.yaw))
            current_error = abs(normalize(float(step.value) - pose.yaw))
            return max(0.0, initial_error - current_error), self.limits.angular_tolerance_rad
        travelled = hypot(pose.x - self._origin.x, pose.y - self._origin.y)
        return travelled, self.limits.linear_tolerance_m

    def _rotate(self, pose: Pose2D, target_yaw: float) -> tuple[VelocityCommand, bool]:
        error = normalize(target_yaw - pose.yaw)
        if abs(error) <= self.limits.angular_tolerance_rad:
            return VelocityCommand(), True
        speed = max(
            -self.limits.max_angular_rps,
            min(self.limits.max_angular_rps, 1.2 * error),
        )
        return VelocityCommand(angular_z=speed), False

    def _straight(self, pose: Pose2D, distance: float) -> tuple[VelocityCommand, bool]:
        assert self._origin is not None
        travelled = hypot(pose.x - self._origin.x, pose.y - self._origin.y)
        remaining = abs(distance) - travelled
        if remaining <= self.limits.linear_tolerance_m:
            return VelocityCommand(), True
        sign = 1.0 if distance >= 0.0 else -1.0
        speed = min(self.limits.max_linear_mps, 0.6 * remaining)
        return VelocityCommand(linear_x=sign * speed), False

    def _exit_zone(self, pose: Pose2D) -> tuple[VelocityCommand, bool]:
        assert self.profile.zone is not None
        if not self.profile.zone.contains(pose):
            return VelocityCommand(), True
        return VelocityCommand(linear_x=self.limits.max_linear_mps), False


def load_narrow_zones(
    document: Mapping[str, Any], *, map_name: str
) -> dict[str, NarrowZoneProfile]:
    declared = str(document.get("map_name", ""))
    if declared != map_name:
        raise NarrowZoneConfigError(
            f"협로 profile은 {declared!r} 지도 값인데 현재 지도는 {map_name!r}이다"
        )
    raw_zones = document.get("zones")
    if not isinstance(raw_zones, Mapping):
        raise NarrowZoneConfigError("zones mapping이 필요하다")
    return {
        str(destination): _parse_profile(str(destination), body)
        for destination, body in raw_zones.items()
    }


def _parse_profile(destination: str, raw: Any) -> NarrowZoneProfile:
    if not isinstance(raw, Mapping):
        return NarrowZoneProfile(
            destination_code=destination,
            enabled=False,
            approach_required=True,
            entry_pose=None,
            entry_zone=None,
            zone=None,
            enter=(),
            exit=(),
            dock_target=None,
            exit_target=None,
            measurement=MeasurementState(),
            issues=("profile_not_mapping",),
        )
    issues: list[str] = []
    entry = _pose(raw.get("entry"), f"{destination}.entry", issues)
    entry_zone = _zone(
        raw.get("entry_zone"), entry, f"{destination}.entry_zone", issues
    )
    zone = _zone(raw.get("zone"), entry, f"{destination}.zone", issues)
    enter = _steps(raw.get("enter"), f"{destination}.enter", issues)
    exit_steps = _steps(raw.get("exit"), f"{destination}.exit", issues)
    dock_target = _pose(raw.get("dock_target"), f"{destination}.dock_target", issues)
    exit_target = _pose(raw.get("exit_target"), f"{destination}.exit_target", issues)
    departure_triggers = _circular_triggers(
        raw.get("departure_triggers"), f"{destination}.departure_triggers", issues
    )
    exit_completion_radius_m = _positive_optional_float(
        raw.get("exit_completion_radius"),
        f"{destination}.exit_completion_radius",
        issues,
    )
    entry_passage = _entry_passage(
        raw.get("entry_passage"), f"{destination}.entry_passage", issues
    )
    measured_raw = raw.get("measured")
    measured = measured_raw if isinstance(measured_raw, Mapping) else {}
    measurement = MeasurementState(
        entry_pose=measured.get("entry_pose") is True,
        dock_pose=measured.get("dock_pose") is True,
        enter=measured.get("enter") is True,
        exit=measured.get("exit") is True,
    )
    return NarrowZoneProfile(
        destination_code=destination,
        enabled=bool(raw.get("enabled", True)),
        approach_required=bool(raw.get("approach_required", True)),
        entry_pose=entry,
        entry_zone=entry_zone,
        zone=zone,
        enter=enter,
        exit=exit_steps,
        dock_target=dock_target,
        exit_target=exit_target,
        measurement=measurement,
        marker_id=str(raw["marker_id"]) if raw.get("marker_id") is not None else None,
        metadata=dict(measured),
        issues=tuple(issues),
        departure_triggers=departure_triggers,
        exit_completion_radius_m=exit_completion_radius_m,
        entry_passage=entry_passage,
    )


def _entry_passage(
    raw: Any, where: str, issues: list[str]
) -> EntryPassageConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        issues.append(f"{where}_not_mapping")
        return None
    local_issues: list[str] = []
    doorway = _pose(raw.get("doorway"), f"{where}.doorway", local_issues)
    inside_turn = _pose(
        raw.get("inside_turn"), f"{where}.inside_turn", local_issues
    )
    try:
        dock_yaw = float(raw["dock_yaw"])
        entry_yaw_tolerance_rad = float(raw["entry_yaw_tolerance_rad"])
        entry_straight_speed_mps = float(raw["entry_straight_speed_mps"])
        heading_correction_max_rps = float(raw["heading_correction_max_rps"])
        recovery_distance_m = float(raw["recovery_distance_m"])
        recovery_speed_mps = float(raw["recovery_speed_mps"])
        recovery_max_attempts_raw = raw["recovery_max_attempts"]
        recovery_max_attempts = int(recovery_max_attempts_raw)
        recovery_timeout_s = float(raw["recovery_timeout_s"])
    except (KeyError, TypeError, ValueError, OverflowError):
        local_issues.append(f"{where}_invalid")
    else:
        numbers = (
            dock_yaw,
            entry_yaw_tolerance_rad,
            entry_straight_speed_mps,
            heading_correction_max_rps,
            recovery_distance_m,
            recovery_speed_mps,
            recovery_timeout_s,
        )
        poses = (doorway, inside_turn)
        if not all(isfinite(value) for value in numbers):
            local_issues.append(f"{where}_not_finite")
        if any(
            pose is not None
            and not all(isfinite(value) for value in (pose.x, pose.y, pose.yaw))
            for pose in poses
        ):
            local_issues.append(f"{where}_pose_not_finite")
        if (
            entry_yaw_tolerance_rad <= 0.0
            or entry_straight_speed_mps <= 0.0
            or heading_correction_max_rps <= 0.0
            or recovery_distance_m < 0.0
            or recovery_speed_mps <= 0.0
            or recovery_timeout_s <= 0.0
        ):
            local_issues.append(f"{where}_limits_invalid")
        if (
            isinstance(recovery_max_attempts_raw, bool)
            or recovery_max_attempts <= 0
            or recovery_max_attempts != recovery_max_attempts_raw
        ):
            local_issues.append(f"{where}_attempts_invalid")
    if doorway is None or inside_turn is None:
        local_issues.append(f"{where}_pose_missing")
    if local_issues:
        issues.extend(local_issues)
        return None
    return EntryPassageConfig(
        doorway=doorway,
        inside_turn=inside_turn,
        dock_yaw=dock_yaw,
        entry_yaw_tolerance_rad=entry_yaw_tolerance_rad,
        entry_straight_speed_mps=entry_straight_speed_mps,
        heading_correction_max_rps=heading_correction_max_rps,
        recovery_distance_m=recovery_distance_m,
        recovery_speed_mps=recovery_speed_mps,
        recovery_max_attempts=recovery_max_attempts,
        recovery_timeout_s=recovery_timeout_s,
    )


def _positive_optional_float(
    raw: Any, where: str, issues: list[str]
) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        issues.append(f"{where}_invalid")
        return None
    if value <= 0.0:
        issues.append(f"{where}_not_positive")
        return None
    return value


def _circular_triggers(
    raw: Any, where: str, issues: list[str]
) -> tuple[CircularTrigger, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        issues.append(f"{where}_not_list")
        return ()
    triggers: list[CircularTrigger] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            issues.append(f"{where}[{index}]_not_mapping")
            continue
        try:
            trigger = CircularTrigger(
                x=float(item["x"]),
                y=float(item["y"]),
                radius=float(item["radius"]),
            )
        except (KeyError, TypeError, ValueError):
            issues.append(f"{where}[{index}]_invalid")
            continue
        if trigger.radius <= 0.0:
            issues.append(f"{where}[{index}]_radius_not_positive")
            continue
        triggers.append(trigger)
    return tuple(triggers)


def _pose(raw: Any, where: str, issues: list[str]) -> Pose2D | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        issues.append(f"{where}_not_mapping")
        return None
    try:
        return Pose2D(float(raw["x"]), float(raw["y"]), float(raw["yaw"]))
    except (KeyError, TypeError, ValueError):
        issues.append(f"{where}_invalid")
        return None


def _zone(
    raw: Any, entry: Pose2D | None, where: str, issues: list[str]
) -> OrientedZone | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        issues.append(f"{where}_not_mapping")
        return None
    try:
        x = float(raw.get("x", entry.x if entry else None))
        y = float(raw.get("y", entry.y if entry else None))
        yaw = float(raw.get("yaw", entry.yaw if entry else None))
        length, width = float(raw["length"]), float(raw["width"])
        if length <= 0.0 or width <= 0.0:
            raise ValueError
        return OrientedZone(x, y, yaw, length, width)
    except (KeyError, TypeError, ValueError):
        issues.append(f"{where}_invalid")
        return None


def _steps(raw: Any, where: str, issues: list[str]) -> tuple[MotionStep, ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return ()
    parsed: list[MotionStep] = []
    try:
        for item in raw:
            if not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) != 2:
                raise NarrowZoneConfigError(f"{where}: [종류, 값] 형식이 아니다")
            parsed.append(MotionStep(str(item[0]), item[1]))
    except (NarrowZoneConfigError, TypeError, ValueError):
        issues.append(f"{where}_invalid")
        return ()
    return tuple(parsed)
