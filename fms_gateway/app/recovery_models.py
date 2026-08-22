"""Strict HTTP contract for finalized, trainable recovery executions."""

from __future__ import annotations

from datetime import datetime
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class RecoveryStateV1Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    robot_x_m: float
    robot_y_m: float
    robot_yaw_rad: float
    goal_x_m: float
    goal_y_m: float
    risk_bbox_center_x_norm: float
    risk_bbox_center_y_norm: float
    risk_confidence: float
    vlm_uncertainty: float

    @model_validator(mode="after")
    def validate_frozen_state(self):
        from model.vlm_rl.shared.contracts import RecoveryStateV1

        RecoveryStateV1(**self.model_dump())
        return self


class RecoveryPerceptionEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")

    class_name: Literal["person", "obstacle"]
    confidence: float
    bbox_xyxy_norm: tuple[float, float, float, float]

    @model_validator(mode="after")
    def validate_normalized_detection(self):
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("evidence confidence must be within 0..1")
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in self.bbox_xyxy_norm):
            raise ValueError("evidence bbox must be normalized")
        left, top, right, bottom = self.bbox_xyxy_norm
        if left >= right or top >= bottom:
            raise ValueError("evidence bbox must have positive area")
        return self


class RecoveryProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    recovery_episode_uuid: str
    step_no: int
    device_id: str
    map_name: str
    map_revision: str
    trigger_type: Literal["blocked", "person", "low_visibility", "localization"]
    state_schema_id: Literal["trihouse.recovery-state.v1"]
    state: RecoveryStateV1Payload
    perception_evidence: list[RecoveryPerceptionEvidence]
    vlm_lineage: dict[str, str]
    policy_lineage: dict[str, str]
    selected_skill_id: int
    selected_skill_name: str
    selected_coord: tuple[float, float, float]
    candidate_evidence: list[dict[str, Any]] = Field(default_factory=list)
    safety_gate_enabled: bool

    @model_validator(mode="after")
    def validate_skill_and_identity(self):
        from uuid import UUID

        UUID(self.proposal_id)
        UUID(self.recovery_episode_uuid)
        if self.step_no <= 0:
            raise ValueError("step_no must be positive")
        if not self.device_id.strip() or not self.map_name.strip() or not self.map_revision.strip():
            raise ValueError("device and map identity must not be empty")
        if isinstance(self.selected_skill_id, bool) or not 0 <= self.selected_skill_id < len(SKILL_NAMES):
            raise ValueError("selected skill is outside the frozen ontology")
        if self.selected_skill_name != SKILL_NAMES[self.selected_skill_id]:
            raise ValueError("selected skill name does not match selected skill id")
        if not self.perception_evidence:
            raise ValueError("recovery proposal requires perception evidence")
        return self


class RecoveryProposalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str
    decision: Literal["approved", "rejected"]
    reason: str

    @field_validator("worker_id", "reason")
    @classmethod
    def nonempty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("decision identity and reason must not be empty")
        return value
