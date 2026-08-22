"""Frozen VLM+RL state/action contract used by DB export and model code."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any


STATE_DIM = 9
COORD_DIM = 3
N_SKILLS = 5
SKILL_NAMES = (
    "BACKUP",
    "REROUTE_LEFT",
    "REROUTE_RIGHT",
    "WAIT_REOBSERVE",
    "REJOIN",
)
SKILL_TO_ACTION_FAMILY = {
    0: "retreat",
    1: "detour",
    2: "detour",
    3: "wait",
    4: "rejoin",
}
# Backward-compatible import for older completion senders. New code must use
# the family name because left/right remain distinct model skills.
SKILL_TO_ACTION_TYPE = SKILL_TO_ACTION_FAMILY


@dataclass(frozen=True)
class RecoveryStateV1:
    """Named external contract for the frozen nine-value model state."""

    robot_x_m: float
    robot_y_m: float
    robot_yaw_rad: float
    goal_x_m: float
    goal_y_m: float
    risk_bbox_center_x_norm: float
    risk_bbox_center_y_norm: float
    risk_confidence: float
    vlm_uncertainty: float
    state_schema_id: str = field(default="trihouse.recovery-state.v1", init=False)

    def __post_init__(self) -> None:
        values = self.to_vector()
        if not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            for value in values
        ):
            raise ValueError("RecoveryStateV1 values must be finite numbers")
        normalized = values[5:]
        if any(value < 0.0 or value > 1.0 for value in normalized):
            raise ValueError("normalized RecoveryStateV1 values must be within 0..1")

    def to_vector(self) -> tuple[float, ...]:
        return (
            self.robot_x_m,
            self.robot_y_m,
            self.robot_yaw_rad,
            self.goal_x_m,
            self.goal_y_m,
            self.risk_bbox_center_x_norm,
            self.risk_bbox_center_y_norm,
            self.risk_confidence,
            self.vlm_uncertainty,
        )


@dataclass(frozen=True)
class LearningTransition:
    state: tuple[float, ...]
    skill: int
    coord: tuple[float, float, float]
    reward: float
    next_state: tuple[float, ...]
    done: bool
    meta: dict[str, Any] = field(default_factory=dict)


def validate_transition(item: LearningTransition) -> None:
    """Reject records that cannot be consumed by the frozen TGRPO+SAC model."""
    if len(item.state) != STATE_DIM or len(item.next_state) != STATE_DIM:
        raise ValueError("state vectors must contain exactly 9 finite numbers")
    if not isinstance(item.skill, int) or isinstance(item.skill, bool) or not 0 <= item.skill < N_SKILLS:
        raise ValueError("skill must be within the frozen five-skill ontology")
    if len(item.coord) != COORD_DIM:
        raise ValueError("coord must contain dx, dy, and dyaw")
    if not isinstance(item.done, bool):
        raise ValueError("done must be a boolean episode-terminal flag")
    values = (*item.state, *item.coord, item.reward, *item.next_state)
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) for value in values):
        raise ValueError("transition values must be finite numbers")
    if item.meta.get("is_execution") is not True:
        raise ValueError("only an actually executed recovery action is trainable")
