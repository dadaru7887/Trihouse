"""Canonical recovery motion shared by proposal, Safety, and execution."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .contracts import SKILL_NAMES, SKILL_TO_ACTION_FAMILY


ENVELOPE_RADIUS_M = 0.25
YAW_LIMIT_RAD = math.pi / 3


@dataclass(frozen=True)
class Pose2D:
    x_m: float
    y_m: float
    yaw_rad: float


@dataclass(frozen=True)
class CanonicalRecoveryAction:
    skill: int
    skill_name: str
    action_family: str
    coord: tuple[float, float, float]
    heading_rad: float | None = None
    distance_m: float | None = None
    duration_seconds: float | None = None
    map_target: Pose2D | None = None


def _finite_coord(coord: tuple[float, float, float]) -> tuple[float, float, float]:
    if len(coord) != 3 or not all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        for value in coord
    ):
        raise ValueError("coord must contain three finite numbers")
    return tuple(float(value) for value in coord)


def _bounded_offset(dx: float, dy: float) -> tuple[float, float]:
    distance = math.hypot(dx, dy)
    if distance <= ENVELOPE_RADIUS_M or distance == 0.0:
        return dx, dy
    scale = ENVELOPE_RADIUS_M / distance
    return dx * scale, dy * scale


def _bounded_yaw(value: float) -> float:
    return max(-YAW_LIMIT_RAD, min(YAW_LIMIT_RAD, value))


def canonicalize_recovery_action(
    skill: int,
    coord: tuple[float, float, float],
    robot_pose: Pose2D,
) -> CanonicalRecoveryAction:
    """Convert one policy output into the sole Safety/execution representation."""
    if skill not in SKILL_TO_ACTION_FAMILY:
        raise ValueError("unknown recovery skill")
    dx, dy, dyaw = _finite_coord(coord)
    dx, dy = _bounded_offset(dx, dy)
    dyaw = _bounded_yaw(dyaw)
    common = {
        "skill": skill,
        "skill_name": SKILL_NAMES[skill],
        "action_family": SKILL_TO_ACTION_FAMILY[skill],
    }

    if skill == 0:
        distance = math.hypot(dx, dy)
        return CanonicalRecoveryAction(
            **common,
            coord=(-distance, 0.0, 0.0),
            distance_m=distance,
        )
    if skill in (1, 2):
        heading = math.atan2(dy, dx)
        if (skill == 1 and heading <= 0.0) or (skill == 2 and heading >= 0.0):
            raise ValueError("coord direction conflicts with selected detour skill")
        return CanonicalRecoveryAction(
            **common,
            coord=(dx, dy, dyaw),
            heading_rad=heading,
            distance_m=math.hypot(dx, dy),
        )
    if skill == 3:
        return CanonicalRecoveryAction(
            **common,
            coord=(0.0, 0.0, 0.0),
            duration_seconds=1.0,
        )

    cos_yaw = math.cos(robot_pose.yaw_rad)
    sin_yaw = math.sin(robot_pose.yaw_rad)
    target = Pose2D(
        x_m=robot_pose.x_m + dx * cos_yaw - dy * sin_yaw,
        y_m=robot_pose.y_m + dx * sin_yaw + dy * cos_yaw,
        yaw_rad=robot_pose.yaw_rad + dyaw,
    )
    return CanonicalRecoveryAction(
        **common,
        coord=(dx, dy, dyaw),
        map_target=target,
    )
