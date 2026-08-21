"""Strict HTTP contract for finalized, trainable recovery executions."""

from __future__ import annotations

from datetime import datetime
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from model.vlm_rl.shared.contracts import SKILL_NAMES


class RecoveryLearningTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    state: tuple[float, float, float, float, float, float, float, float, float]
    skill: int
    skill_name: str
    coord: tuple[float, float, float]
    reward: float
    next_state: tuple[float, float, float, float, float, float, float, float, float]
    done: bool
    meta: dict[str, Any]

    @field_validator("state", "coord", "next_state")
    @classmethod
    def finite_vectors(cls, values: tuple[float, ...]) -> tuple[float, ...]:
        if not all(math.isfinite(value) for value in values):
            raise ValueError("transition vectors must contain only finite numbers")
        return values

    @field_validator("reward")
    @classmethod
    def finite_reward(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("reward must be finite")
        return value

    @model_validator(mode="after")
    def frozen_skill_and_execution(self):
        if isinstance(self.skill, bool) or not 0 <= self.skill < len(SKILL_NAMES):
            raise ValueError("skill must be within the frozen five-skill ontology")
        if self.skill_name != SKILL_NAMES[self.skill]:
            raise ValueError("skill_name does not match skill")
        if self.meta.get("is_execution") is not True:
            raise ValueError("meta.is_execution must be true")
        return self


class RecoveryStepCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_status: Literal["succeeded", "failed", "cancelled"]
    outcome_class: Literal["safe", "boundary", "critical"]
    completed_at: datetime
    is_terminal: bool
    reward_components: dict[str, float]
    transition: RecoveryLearningTransition

    @field_validator("reward_components")
    @classmethod
    def finite_reward_components(cls, values: dict[str, float]) -> dict[str, float]:
        if not all(math.isfinite(value) for value in values.values()):
            raise ValueError("reward components must be finite")
        return values

    @model_validator(mode="after")
    def episode_terminal_semantics(self):
        if self.transition.done is not self.is_terminal:
            raise ValueError("transition.done must match whether this is the final episode step")
        return self


class RecoveryStepAcknowledgement(BaseModel):
    message_id: str
    recovery_step_id: int
    execution_status: str
    acknowledged: Literal[True] = True
