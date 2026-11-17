"""Convert an actual Pinky recovery result into the frozen offline-training tuple."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Sequence

from vision_ai.utils.contracts import RecoveryStateV1


MISSION_REJOINED_THRESHOLD_M = 0.15

# 몸 경계에서 잰 충돌급 거리.
#
# 원본은 회전 중심에서 잰 0.085 m 였다 — 발자국 내접원 0.06 m 에 센서·제어 오차
# 0.025 m 를 더한 값이다. 그런데 그때 실제로 넣던 값은 LiDAR 최소 거리라, 정의는
# 몸 기준이고 측정은 센서 기준이라 둘이 같은 것을 재지 않았다. 이제 로봇이 몸
# 경계 기준 여유를 직접 보고하므로, 같은 물리적 의미를 유지하려면 내접원을 뺀
# 나머지인 오차 여유만 남는다.
TERMINAL_CRITICAL_BODY_CLEARANCE_M = 0.025

# 이 보상이 어떤 여유 정의로 계산됐는지. 정의가 바뀌면 이전 데이터와 reward 의
# 의미가 달라지는데 원본 스캔이 없어 소급 재계산이 불가능하다. 학습이 두 정의를
# 말없이 섞지 않도록 전이마다 이름을 남긴다.
CLEARANCE_DEFINITION = "path_forward_body_v2"

# EN: Reward math below is migrated from dev_driving; HTTP/DB packaging is Trihouse integration.
# KO: 아래 reward 수식은 dev_driving 이식본이고 HTTP/DB 포장은 Trihouse 연결부다.

def _distance_to_goal(state: Sequence[float]) -> float:
    return math.hypot(float(state[3]) - float(state[0]), float(state[4]) - float(state[1]))


def _real_reward(
    pre_state: Sequence[float],
    next_state: Sequence[float],
    *,
    clearance_after_m: float,
    body_clearance_after_m: float,
    elapsed_seconds: float,
    safety_intervened: bool,
) -> tuple[float, dict[str, float], bool]:
    """Preserve the original dev_driving constants with two separated clearances.

    The shaping term asks "can this robot keep going this way", which is a question
    about the direction of travel. The terminal term asks "is this pose already a
    collision", which is true from any direction. Feeding one omnidirectional
    minimum into both made a wall the robot was safely passing look like an
    obstacle it was about to hit.
    """
    for name, value in (
        ("clearance", clearance_after_m),
        ("body clearance", body_clearance_after_m),
    ):
        if value < 0.0 or not math.isfinite(value):
            raise ValueError(
                f"observed non-negative {name} is required for training data"
            )
    terminal_critical = body_clearance_after_m < TERMINAL_CRITICAL_BODY_CLEARANCE_M
    if terminal_critical:
        return -100.0, {"terminal_critical": 1.0}, True
    progress = _distance_to_goal(pre_state) - _distance_to_goal(next_state)
    clearance_cost = max(0.0, 0.3 - clearance_after_m) ** 2
    intervention = 1.0 if safety_intervened else 0.0
    rejoined = _distance_to_goal(next_state) < MISSION_REJOINED_THRESHOLD_M
    rejoin_bonus = 10.0 if rejoined else 0.0
    total = (
        progress - 5.0 * clearance_cost - 2.0 * intervention
        - 0.1 * elapsed_seconds + rejoin_bonus
    )
    return total, {
        "progress": progress,
        "clearance_cost": clearance_cost,
        "intervention": intervention,
        "time_cost": elapsed_seconds,
        "rejoin_bonus": rejoin_bonus,
        "path_clearance_m": clearance_after_m,
        "body_clearance_m": body_clearance_after_m,
    }, False


def build_completion(
    proposal: dict[str, Any],
    execution: dict[str, Any],
    next_state: Sequence[float],
) -> dict[str, Any]:
    state = RecoveryStateV1(**proposal["state"]).to_vector()
    next_vector = tuple(float(value) for value in next_state)
    if len(next_vector) != 9 or not all(math.isfinite(value) for value in next_vector):
        raise ValueError("next_state must contain nine finite values")
    reward, components, terminal_critical = _real_reward(
        state,
        next_vector,
        clearance_after_m=float(execution["clearance_after_m"]),
        body_clearance_after_m=float(execution["body_clearance_after_m"]),
        elapsed_seconds=float(execution["elapsed_seconds"]),
        safety_intervened=bool(execution["safety_intervened"]),
    )
    status = execution["status"]
    if status not in {"succeeded", "failed", "cancelled"}:
        raise ValueError("execution status is outside the completion contract")
    outcome_class = "critical" if terminal_critical else (
        "safe" if execution["success"] else "boundary"
    )
    done = bool(execution["terminal"])
    return {
        "execution_status": status,
        "outcome_class": outcome_class,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "is_terminal": done,
        "reward_components": components,
        "transition": {
            "schema_version": 1,
            "state": list(state),
            "skill": proposal["selected_skill_id"],
            "skill_name": proposal["selected_skill_name"],
            "coord": list(proposal["selected_coord"]),
            "reward": reward,
            "next_state": list(next_vector),
            "done": done,
            "meta": {
                "is_execution": True,
                "proposal_id": proposal["proposal_id"],
                "command_id": execution["command_id"],
                "reward_source": "dev_driving.real_reward",
                # 이 전이의 reward 가 어떤 여유 정의로 계산됐는지. 정의가 다른
                # 전이를 학습이 말없이 섞지 않도록 값마다 이름을 붙여 둔다.
                "clearance_definition": CLEARANCE_DEFINITION,
            },
        },
    }
