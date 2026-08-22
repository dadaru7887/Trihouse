"""Fleet가 Nav2 목표와 협로 profile을 고르는 순수 routing 경계."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from trihouse_pinky_docking.narrow_zone import NarrowZoneProfile, Pose2D


@dataclass(frozen=True)
class NarrowApproachDecision:
    allowed: bool
    nav_target: Pose2D | None
    profile: NarrowZoneProfile | None = None
    reason_code: str | None = None
    reason: str = ""


def requires_narrow_profile(destination_code: str) -> bool:
    """현재 location naming 계약에서 storage loading dock인지 판정한다."""
    return "_storage_loading_dock_" in destination_code


def select_approach(
    profiles: Mapping[str, NarrowZoneProfile],
    destination_code: str,
    requested_target: Pose2D,
    *,
    calibration: bool = False,
) -> NarrowApproachDecision:
    """일반 목적지는 그대로, 협로 창고는 검증된 entry로만 보낸다."""
    profile = profiles.get(destination_code)
    if profile is None:
        if requires_narrow_profile(destination_code):
            return NarrowApproachDecision(
                False,
                None,
                reason_code="NARROW_PROFILE_MISSING",
                reason="창고 협로 profile이 catalog에 없다",
            )
        return NarrowApproachDecision(True, requested_target)
    if not profile.approach_required:
        return NarrowApproachDecision(True, requested_target)
    if profile.direction_readiness_code("enter") != "READY" and not (
        calibration and profile.calibration_ready("enter")
    ):
        return NarrowApproachDecision(
            False,
            None,
            profile=profile,
            reason_code=profile.readiness_code,
            reason=profile.readiness_reason,
        )
    return NarrowApproachDecision(True, profile.entry_pose, profile=profile)


def departure_profile(
    profiles: Mapping[str, NarrowZoneProfile], current_pose: Pose2D
) -> NarrowZoneProfile | None:
    """현재 도킹 zone을 찾는다. readiness와 무관하게 갇힌 profile은 숨기지 않는다."""
    for profile in profiles.values():
        if profile.zone is not None and profile.zone.contains(current_pose):
            return profile
    return None
