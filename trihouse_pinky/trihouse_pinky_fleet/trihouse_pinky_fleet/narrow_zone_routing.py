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


def entry_motion_strategy(profile: NarrowZoneProfile) -> str:
    """설정에 명시된 출입구 방식만 선택해 fleet와 테스트의 판단을 일치시킨다."""
    return (
        "warehouse_entry"
        if profile.entry_passage is not None
        else "legacy_narrow_zone"
    )


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
    """현재 도킹 zone 또는 대기점 출발 반경의 공통 탈출 profile을 찾는다."""
    for profile in profiles.values():
        if any(trigger.contains(current_pose) for trigger in profile.departure_triggers):
            return profile
        if profile.zone is not None and profile.zone.contains(current_pose):
            return profile
    return None


def entry_handoff_reached(
    profile: NarrowZoneProfile, current_pose: Pose2D
) -> bool:
    """Whether Nav2 has entered the boundary where rule control takes ownership.

    Nav2가 규칙 제어에 제어권을 넘길 입구 구역에 들어왔는지 판정한다.
    """
    return profile.entry_zone is not None and profile.entry_zone.contains(current_pose)
