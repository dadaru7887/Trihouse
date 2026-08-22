"""창고 협로의 설정, 기하, 결정론적 속도 제어를 한 곳에서 소유한다.

이 모듈은 ROS를 import하지 않는다. Fleet/도킹 노드는 여기서 나온 속도 명령을
`cmd_vel_dock`으로 전달하고, 실제 모터 입력은 safety supervisor가 단독 소유한다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import atan2, cos, hypot, sin
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
class NarrowZoneProfile:
    destination_code: str
    enabled: bool
    approach_required: bool
    entry_pose: Pose2D | None
    zone: OrientedZone | None
    enter: tuple[MotionStep, ...]
    exit: tuple[MotionStep, ...]
    dock_target: Pose2D | None
    exit_target: Pose2D | None
    measurement: MeasurementState
    marker_id: str | None = None
    metadata: Mapping[str, Any] | None = None
    issues: tuple[str, ...] = ()

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
                self.zone is None
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
        if not self.enabled or self.zone is None:
            return False
        if direction == ENTER:
            return bool(self.entry_pose and self.enter and self.dock_target)
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


def normalize(angle: float) -> float:
    return atan2(sin(angle), cos(angle))


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
        return True

    def cancel(self, reason: str = "canceled") -> None:
        if not self.is_complete:
            self.failure = reason

    def advance(self, pose: Pose2D, *, now_s: float) -> VelocityCommand:
        if not self._started or self.failure is not None or self.is_complete:
            return VelocityCommand()
        if now_s - self._step_started_s > self.limits.step_timeout_s:
            self.failure = "step_timeout"
            return VelocityCommand()

        step = self.steps[self.step_index]
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
        return VelocityCommand()

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
            destination,
            False,
            True,
            None,
            None,
            (),
            (),
            None,
            None,
            MeasurementState(),
            issues=("profile_not_mapping",),
        )
    issues: list[str] = []
    entry = _pose(raw.get("entry"), f"{destination}.entry", issues)
    zone = _zone(raw.get("zone"), entry, f"{destination}.zone", issues)
    enter = _steps(raw.get("enter"), f"{destination}.enter", issues)
    exit_steps = _steps(raw.get("exit"), f"{destination}.exit", issues)
    dock_target = _pose(raw.get("dock_target"), f"{destination}.dock_target", issues)
    exit_target = _pose(raw.get("exit_target"), f"{destination}.exit_target", issues)
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
        zone=zone,
        enter=enter,
        exit=exit_steps,
        dock_target=dock_target,
        exit_target=exit_target,
        measurement=measurement,
        marker_id=str(raw["marker_id"]) if raw.get("marker_id") is not None else None,
        metadata=dict(measured),
        issues=tuple(issues),
    )


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
