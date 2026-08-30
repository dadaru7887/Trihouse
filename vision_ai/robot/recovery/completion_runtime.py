"""Convert an actual Pinky recovery result into the frozen offline-training tuple."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Sequence

from vision_ai.utils.contracts import RecoveryStateV1


MISSION_REJOINED_THRESHOLD_M = 0.15
TERMINAL_CRITICAL_DIST_M = 0.085

# EN: Reward math below is migrated from dev_driving; HTTP/DB packaging is Trihouse integration.
# KO: 아래 reward 수식은 dev_driving 이식본이고 HTTP/DB 포장은 Trihouse 연결부다.

def _distance_to_goal(state: Sequence[float]) -> float:
    return math.hypot(float(state[3]) - float(state[0]), float(state[4]) - float(state[1]))


def _real_reward(
    pre_state: Sequence[float],
    next_state: Sequence[float],
    *,
    clearance_after_m: float,
    elapsed_seconds: float,
    safety_intervened: bool,
) -> tuple[float, dict[str, float], bool]:
    """Preserve the original dev_driving real_reward constants and equation."""
    if clearance_after_m < 0.0 or not math.isfinite(clearance_after_m):
        raise ValueError("observed non-negative clearance is required for training data")
    terminal_critical = clearance_after_m < TERMINAL_CRITICAL_DIST_M
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
            },
        },
    }
