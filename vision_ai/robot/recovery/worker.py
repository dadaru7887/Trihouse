"""Dependency-injected realtime perception → VLM/RL → proposal boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Protocol, Sequence
from uuid import uuid4

from vision_ai.utils.contracts import RecoveryStateV1, SKILL_NAMES
from vision_ai.utils.motion_plan import Pose2D, canonicalize_recovery_action

from .navigation_context import NavigationContext
from .trigger import should_trigger_recovery


@dataclass(frozen=True)
class DetectionEvidence:
    class_name: str
    confidence: float
    bbox_xyxy_norm: tuple[float, float, float, float]
    track_id: str = ""


class Vlm(Protocol):
    model_name: str
    model_revision: str

    def interpret(self, frame: Any, detections: Sequence[DetectionEvidence], goal_text: str) -> dict[str, Any]: ...


class Policy(Protocol):
    policy_name: str
    checkpoint_sha256: str

    def select(self, state: tuple[float, ...]) -> tuple[int, tuple[float, float, float]]: ...


class SkillSelector(Protocol):
    """Distilled selector that may only re-rank already-bounded candidates."""

    selector_name: str
    ensemble_sha256: str

    def select_skill_or_fallback(self, state: tuple[float, ...]) -> Any: ...


class ProposalClient(Protocol):
    def create(self, payload: dict[str, Any]) -> dict[str, Any]: ...


RISK_VALUE = {"low": 0, "moderate": 1, "critical": 2}


def _validated_worst_observation(vlm_result: dict[str, Any]) -> dict[str, Any] | None:
    observations = vlm_result.get("observations")
    uncertainty = vlm_result.get("uncertainty")
    if not isinstance(observations, list) or not observations:
        return None
    if not isinstance(uncertainty, (int, float)) or not math.isfinite(uncertainty) or not 0 <= uncertainty <= 1:
        return None
    for observation in observations:
        if not isinstance(observation, dict):
            return None
        bbox = observation.get("bbox_norm")
        confidence = observation.get("confidence")
        if (
            observation.get("semantic_label") not in {"person", "obstacle", "unknown_dynamic"}
            or observation.get("risk") not in RISK_VALUE
            or not isinstance(bbox, list)
            or len(bbox) != 4
            or not all(isinstance(value, (int, float)) and 0 <= value <= 1 for value in bbox)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            return None
    return max(
        observations,
        key=lambda item: (RISK_VALUE[item["risk"]], float(item["confidence"])),
    )


class RecoveryInferenceWorker:
    def __init__(self, vlm: Vlm, policy: Policy, proposal_client: ProposalClient,
                 *, safety_gate_enabled: bool = True,
                 skill_selector: SkillSelector | None = None):
        self.vlm = vlm
        self.policy = policy
        self.proposal_client = proposal_client
        self.safety_gate_enabled = safety_gate_enabled
        self.skill_selector = skill_selector

    def process(
        self,
        frame: Any,
        detections: Sequence[DetectionEvidence],
        context: NavigationContext,
    ) -> dict[str, Any] | None:
        if not should_trigger_recovery(detections, context):
            return None
        goal_text = "The robot is navigating a warehouse aisle toward the next waypoint."
        vlm_result = self.vlm.interpret(frame, detections, goal_text)
        worst = _validated_worst_observation(vlm_result)
        if worst is None:
            return None
        x0, y0, x1, y1 = (float(value) for value in worst["bbox_norm"])
        state = RecoveryStateV1(
            robot_x_m=context.robot_pose[0],
            robot_y_m=context.robot_pose[1],
            robot_yaw_rad=context.robot_pose[2],
            goal_x_m=context.goal_pose[0],
            goal_y_m=context.goal_pose[1],
            risk_bbox_center_x_norm=(x0 + x1) / 2,
            risk_bbox_center_y_norm=(y0 + y1) / 2,
            risk_confidence=float(worst["confidence"]),
            vlm_uncertainty=float(vlm_result["uncertainty"]),
        )
        pose = Pose2D(*context.robot_pose)
        candidate_evidence: list[dict[str, Any]] = []
        group_sampler = getattr(self.policy, "select_group", None)
        if callable(group_sampler):
            ranked: list[tuple[float, int, tuple[float, float, float], Any]] = []
            for candidate_index, (candidate_skill, candidate_coord, log_prob) in enumerate(
                group_sampler(state.to_vector(), k=3, m=2)
            ):
                try:
                    candidate_action = canonicalize_recovery_action(
                        candidate_skill, candidate_coord, pose
                    )
                except ValueError as error:
                    candidate_evidence.append({
                        "candidate_index": candidate_index,
                        "skill": candidate_skill,
                        "raw_coord": list(candidate_coord),
                        "passed_boundary": False,
                        "reason": str(error),
                    })
                    continue
                dx, dy, _ = candidate_action.coord
                if candidate_action.map_target is not None:
                    target_x, target_y = (
                        candidate_action.map_target.x_m,
                        candidate_action.map_target.y_m,
                    )
                else:
                    cos_yaw, sin_yaw = math.cos(pose.yaw_rad), math.sin(pose.yaw_rad)
                    target_x = pose.x_m + dx * cos_yaw - dy * sin_yaw
                    target_y = pose.y_m + dx * sin_yaw + dy * cos_yaw
                goal_distance = math.hypot(
                    context.goal_pose[0] - target_x,
                    context.goal_pose[1] - target_y,
                )
                candidate_evidence.append({
                    "candidate_index": candidate_index,
                    "skill": candidate_skill,
                    "skill_name": SKILL_NAMES[candidate_skill],
                    "raw_coord": list(candidate_coord),
                    "canonical_coord": list(candidate_action.coord),
                    "skill_log_prob": log_prob,
                    "passed_boundary": True,
                    "goal_distance_m": goal_distance,
                })
                ranked.append((goal_distance, candidate_skill, candidate_action.coord, candidate_action))
            if not ranked:
                return None
            _, skill, coord, action = min(ranked, key=lambda item: item[0])
            skill_selection, learned_skill = self._selector_evidence(state.to_vector())
            if learned_skill is not None:
                preferred = [item for item in ranked if item[1] == learned_skill]
                if preferred:
                    _, skill, coord, action = min(preferred, key=lambda item: item[0])
                    skill_selection["source"] = "distilled_ensemble"
                    skill_selection["use_learned"] = True
                else:
                    # The learned skill stays on the record for audit, but it was not
                    # applied: the motion boundary discarded every candidate carrying it.
                    skill_selection["reason"] = (
                        f"{skill_selection['reason']}; no bounded candidate for "
                        f"{SKILL_NAMES[learned_skill]}"
                    )
        else:
            skill, coord = self.policy.select(state.to_vector())
            action = canonicalize_recovery_action(skill, coord, pose)
            skill_selection, learned_skill = self._selector_evidence(state.to_vector())
            if learned_skill is not None:
                # A single-select policy offers no candidate group to re-rank, so the
                # distilled verdict is recorded without being applied.
                skill_selection["reason"] = (
                    f"{skill_selection['reason']}; no candidate group to re-rank"
                )
        named_state = asdict(state)
        named_state.pop("state_schema_id")
        proposal = {
            "proposal_id": str(uuid4()),
            "recovery_episode_uuid": str(uuid4()),
            "step_no": 1,
            "device_id": context.device_id,
            "map_name": context.map_name,
            "map_revision": context.map_revision,
            "trigger_type": "person" if any(d.class_name == "person" for d in detections) else "blocked",
            "state_schema_id": state.state_schema_id,
            "state": named_state,
            "perception_evidence": [asdict(item) for item in detections],
            "vlm_lineage": {"model": self.vlm.model_name, "revision": self.vlm.model_revision},
            "policy_lineage": {
                "model": self.policy.policy_name,
                "checkpoint_sha256": self.policy.checkpoint_sha256,
            },
            "selected_skill_id": skill,
            "selected_skill_name": SKILL_NAMES[skill],
            "selected_coord": list(action.coord),
            "candidate_evidence": candidate_evidence,
            "skill_selection": skill_selection,
            "safety_gate_enabled": self.safety_gate_enabled,
        }
        response = self.proposal_client.create(proposal)
        return {**response, "_local_proposal": proposal}

    def _selector_evidence(
        self, state: tuple[float, ...]
    ) -> tuple[dict[str, Any], int | None]:
        """Consult the distilled selector and report the verdict as not yet applied.

        Returns the evidence plus the skill the gate would like to use. Only the caller
        that actually re-ranks bounded candidates may mark the evidence as applied, so
        an unusable verdict can never be recorded as one that steered the robot.
        """
        if self.skill_selector is None:
            return {
                "source": "goal_distance",
                "use_learned": False,
                "reason": "distilled selector is not configured",
            }, None
        decision = self.skill_selector.select_skill_or_fallback(state)
        proposed = decision.skill if decision.use_learned else None
        evidence: dict[str, Any] = {
            "source": "goal_distance_fallback",
            "use_learned": False,
            "entropy": float(decision.entropy),
            "unanimous": bool(decision.unanimous),
            "mean_probs": [float(value) for value in decision.mean_probs],
            "reason": decision.reason,
            "learned_skill_id": proposed,
            "learned_skill_name": decision.skill_name if proposed is not None else None,
            "selector_lineage": {
                "model": self.skill_selector.selector_name,
                "ensemble_sha256": self.skill_selector.ensemble_sha256,
            },
        }
        return evidence, proposed

    def observe_state(
        self,
        frame: Any,
        detections: Sequence[DetectionEvidence],
        context: NavigationContext,
    ) -> tuple[float, ...]:
        """Observe post-action State V1 without starting another proposal."""
        vlm_result = self.vlm.interpret(
            frame,
            detections,
            "The robot is navigating a warehouse aisle toward the next waypoint.",
        )
        worst = _validated_worst_observation(vlm_result)
        if worst is None:
            center_x = center_y = confidence = 0.0
            uncertainty = float(vlm_result.get("uncertainty", 1.0))
            if not math.isfinite(uncertainty) or not 0.0 <= uncertainty <= 1.0:
                uncertainty = 1.0
        else:
            x0, y0, x1, y1 = (float(value) for value in worst["bbox_norm"])
            center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
            confidence = float(worst["confidence"])
            uncertainty = float(vlm_result["uncertainty"])
        return RecoveryStateV1(
            robot_x_m=context.robot_pose[0], robot_y_m=context.robot_pose[1],
            robot_yaw_rad=context.robot_pose[2], goal_x_m=context.goal_pose[0],
            goal_y_m=context.goal_pose[1], risk_bbox_center_x_norm=center_x,
            risk_bbox_center_y_norm=center_y, risk_confidence=confidence,
            vlm_uncertainty=uncertainty,
        ).to_vector()
