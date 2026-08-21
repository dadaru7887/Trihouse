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
SKILL_TO_ACTION_TYPE = {
    0: "retreat",
    1: "detour",
    2: "detour",
    3: "wait",
    4: "rejoin",
}


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
