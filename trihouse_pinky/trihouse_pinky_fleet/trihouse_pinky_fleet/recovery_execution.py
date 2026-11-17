"""Robot-side admission rules for an operator-approved recovery action."""

from __future__ import annotations

import re
from typing import Any

SKILL_NAMES = (
    "BACKUP",
    "REROUTE_LEFT",
    "REROUTE_RIGHT",
    "WAIT_REOBSERVE",
    "REJOIN",
)


def recovery_admission_block_reason(
    goal: Any,
    *,
    robot_id: str,
    map_revision: str,
    ready: bool,
    recovery_health_ok: bool,
    safety_available: bool,
    emergency: bool,
    stationary: bool,
    transport_active: bool,
    path_block_reason: str | None = None,
) -> str | None:
    if goal.device_id != robot_id:
        return "DEVICE_ID_MISMATCH"
    if goal.map_revision != map_revision:
        return "MAP_REVISION_MISMATCH"
    if (
        not goal.approval_worker_id
        or re.fullmatch(r"[0-9a-f]{64}", goal.proposal_sha256) is None
        or not goal.approval_id
    ):
        return "APPROVAL_INVALID"
    skill = goal.selected_skill_id
    if (
        isinstance(skill, bool)
        or not 0 <= skill < len(SKILL_NAMES)
        or goal.selected_skill_name != SKILL_NAMES[skill]
    ):
        return "SKILL_MISMATCH"
    if emergency:
        return "EMERGENCY_ACTIVE"
    if not safety_available:
        return "SAFETY_SUPERVISOR_UNAVAILABLE"
    if not recovery_health_ok:
        return "RECOVERY_SENSOR_HEALTH_INVALID"
    if not ready:
        return "ROBOT_NOT_READY"
    if transport_active:
        return "MOTION_BUSY"
    if not stationary:
        return "ROBOT_NOT_STOPPED"
    # 마지막에 두는 이유: 이 검사만 지도를 읽으므로 가장 비싸고, 앞의 값싼 신원·
    # 상태 검사가 이미 거부한 명령에 지도를 조회할 필요가 없다. 그리고 실행 직전에
    # 봐야 "지금 이 순간" 이라는 전제가 유지된다.
    if path_block_reason is not None:
        return f"PATH_NOT_CLEAR:{path_block_reason}"
    return None
