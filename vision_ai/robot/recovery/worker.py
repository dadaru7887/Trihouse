"""Dependency-injected realtime perception -> VLM/RL -> proposal boundary.

    evidence = detection_evidence(detector.detect(frame), person_class_id=1)
    worker.process(frame, evidence, context)          # -> proposal or None

Flow: YOLOE detections -> `DetectionEvidence` (region_id left to right, the
ByteTrack id kept) -> VLM rates every region -> `select_risk_target` links each
observation back to its detection and keeps the riskiest -> State V1, whose box
centre is the YOLOE box, never the box the VLM wrote -> policy -> proposal.

The offline prompt comparison (tooling/vlm_prompt_compare.py) imports the same
conversion and linking, so what it scores is what the robot runs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Protocol, Sequence
from uuid import uuid4

from vision_ai.utils.contracts import RecoveryStateV1, SKILL_NAMES
from vision_ai.utils.motion_plan import Pose2D, canonicalize_recovery_action

from .navigation_context import NavigationContext
from .trigger import should_trigger_recovery


GOAL_TEXT = "The robot is navigating a warehouse aisle toward the next waypoint."


@dataclass(frozen=True)
class DetectionEvidence:
    """One YOLOE detection as the VLM and the proposal see it.

    `region_id` names it within one frame (r1 is leftmost); `track_id` is the
    ByteTrack id that follows it across frames, None when nothing tracked it.
    """

    class_name: str
    confidence: float
    bbox_xyxy_norm: tuple[float, float, float, float]
    track_id: str | None = None
    region_id: str = ""


def detection_evidence(detections: Sequence[Any], *, person_class_id: int) -> list[DetectionEvidence]:
    """Detector output -> evidence numbered r1, r2, ... from the left of the frame.

    A detection without a positive-area YOLOE box is dropped: the Gateway would
    refuse the whole proposal over it.
    """
    boxed = [d for d in detections
             if d.box_xyxy_norm is not None
             and d.box_xyxy_norm[0] < d.box_xyxy_norm[2] and d.box_xyxy_norm[1] < d.box_xyxy_norm[3]]
    boxed.sort(key=lambda d: (d.box_xyxy_norm[0] + d.box_xyxy_norm[2],
                              d.box_xyxy_norm[1] + d.box_xyxy_norm[3]))
    return [
        DetectionEvidence(
            class_name="person" if d.class_id == person_class_id else "obstacle",
            confidence=float(d.confidence),
            bbox_xyxy_norm=tuple(min(max(float(v), 0.0), 1.0) for v in d.box_xyxy_norm),
            track_id=d.track_id or None,
            region_id=f"r{number}",
        )
        for number, d in enumerate(boxed, start=1)
    ]


class Vlm(Protocol):
    """`interpret` returns the parsed JSON plus `raw_response`, `scene_confidence`
    (whatever key the prompt version used) and `prompt_version`."""

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


def validated_observations(vlm_result: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The VLM observations if the whole response keeps the contract, else None."""
    observations = vlm_result.get("observations")
    confidence = vlm_result.get("scene_confidence")
    if not isinstance(observations, list) or not observations:
        return None
    if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
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
    return observations


def box_iou(a: Sequence[float], b: Sequence[float]) -> float:
    """Overlap of two [x0, y0, x1, y1] boxes, 0..1."""
    width = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = width * height
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def link_observations(observations: Sequence[dict[str, Any]],
                      detections: Sequence[DetectionEvidence]) -> dict[int, dict[str, Any]]:
    """{detection index: observation}, one observation per detection.

    By `region_id` when the VLM echoed one it was given; otherwise (a prompt
    that never showed ids) by the largest overlap between the VLM's bbox and a
    YOLOE box. An observation that overlaps nothing, or a detection already
    taken, is left out -- the VLM described something YOLOE did not find.
    """
    by_id = {d.region_id: i for i, d in enumerate(detections) if d.region_id}
    linked: dict[int, dict[str, Any]] = {}
    for observation in observations:
        index = by_id.get(observation.get("region_id"))
        if index is None and isinstance(observation.get("bbox_norm"), list):
            overlaps = [(box_iou(d.bbox_xyxy_norm, observation["bbox_norm"]), i)
                        for i, d in enumerate(detections) if i not in linked]
            best = max(overlaps, default=(0.0, None))
            index = best[1] if best[0] > 0 else None
        if index is not None and index not in linked:
            linked[index] = observation
    return linked


def select_risk_target(vlm_result: dict[str, Any], detections: Sequence[DetectionEvidence]
                       ) -> tuple[dict[str, Any], DetectionEvidence] | None:
    """(riskiest observation, its YOLOE detection), or None.

    Riskiest is the highest risk, then the VLM's confidence in that rating.
    Only observations grounded in a detection compete.
    """
    observations = validated_observations(vlm_result)
    linked = link_observations(observations or [], detections)
    if not linked:
        return None
    index, observation = max(
        linked.items(),
        key=lambda item: (RISK_VALUE[item[1]["risk"]], float(item[1]["confidence"])),
    )
    return observation, detections[index]


class RecoveryInferenceWorker:
    def __init__(self, vlm: Vlm, policy: Policy, proposal_client: ProposalClient,
                 *, safety_gate_enabled: bool = True,
                 skill_selector: SkillSelector | None = None,
                 execution_mode: str = "operator_approved"):
        self.vlm = vlm
        self.policy = policy
        self.proposal_client = proposal_client
        self.safety_gate_enabled = safety_gate_enabled
        self.skill_selector = skill_selector
        # Sent with every proposal: the Gateway auto-approves only `auto_bounded` ones.
        self.execution_mode = execution_mode

    def process(
        self,
        frame: Any,
        detections: Sequence[DetectionEvidence],
        context: NavigationContext,
    ) -> dict[str, Any] | None:
        if not should_trigger_recovery(detections, context):
            return None
        vlm_result = self.vlm.interpret(frame, detections, GOAL_TEXT)
        target = select_risk_target(vlm_result, detections)
        if target is None:
            return None
        observation, detection = target
        x0, y0, x1, y1 = detection.bbox_xyxy_norm
        state = RecoveryStateV1(
            robot_x_m=context.robot_pose[0],
            robot_y_m=context.robot_pose[1],
            robot_yaw_rad=context.robot_pose[2],
            goal_x_m=context.goal_pose[0],
            goal_y_m=context.goal_pose[1],
            risk_bbox_center_x_norm=(x0 + x1) / 2,
            risk_bbox_center_y_norm=(y0 + y1) / 2,
            risk_confidence=float(observation["confidence"]),
            scene_confidence=float(vlm_result["scene_confidence"]),
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
            "vlm_lineage": {
                "model": self.vlm.model_name,
                "revision": self.vlm.model_revision,
                "prompt_version": str(vlm_result.get("prompt_version", "")),
                "response_id": str(vlm_result.get("response_id", "")),
            },
            "policy_lineage": {
                "model": self.policy.policy_name,
                "checkpoint_sha256": self.policy.checkpoint_sha256,
                "execution_mode": self.execution_mode,
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
        vlm_result = self.vlm.interpret(frame, detections, GOAL_TEXT)
        target = select_risk_target(vlm_result, detections)
        if target is None:
            # Nothing grounded to look at: no box, and no confidence in the scene.
            center_x = center_y = confidence = scene_confidence = 0.0
        else:
            observation, detection = target
            x0, y0, x1, y1 = detection.bbox_xyxy_norm
            center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
            confidence = float(observation["confidence"])
            scene_confidence = float(vlm_result["scene_confidence"])
        return RecoveryStateV1(
            robot_x_m=context.robot_pose[0], robot_y_m=context.robot_pose[1],
            robot_yaw_rad=context.robot_pose[2], goal_x_m=context.goal_pose[0],
            goal_y_m=context.goal_pose[1], risk_bbox_center_x_norm=center_x,
            risk_bbox_center_y_norm=center_y, risk_confidence=confidence,
            scene_confidence=scene_confidence,
        ).to_vector()
