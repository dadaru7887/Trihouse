"""Versioned, deterministic classification of structured execution facts."""

from dataclasses import dataclass
from typing import Mapping


CATALOG_VERSION = "v1"

REASON_DOMAINS = {
    "WAYPOINT_REACHED": "none",
    "DOCKING_POSE_VERIFIED": "none",
    "NAV2_PATH_NOT_FOUND": "navigation",
    "NAV2_CONTROLLER_FAILED": "navigation",
    "NAV2_ABORTED": "navigation",
    "GOAL_TOLERANCE_NOT_MET": "navigation",
    "ROBOT_NOT_STOPPED": "navigation",
    "OBSTACLE_BLOCKED_TIMEOUT": "navigation",
    "NARROW_PASSAGE_BLOCKED": "navigation",
    "LOCALIZATION_STALE": "navigation",
    "MAP_POSE_INVALID": "navigation",
    "SAFETY_WORKER_DETECTED": "safety",
    "SAFETY_FALLEN_WORKER_DETECTED": "safety",
    "SAFETY_LATCHED": "safety",
    "BATTERY_RETURN_REQUIRED": "robot",
    "BATTERY_TELEMETRY_INVALID": "robot",
    "SENSOR_TELEMETRY_STALE": "robot",
    "RMF_REPLAN_REPLACED": "integration",
    "RMF_TASK_CANCELLED": "integration",
    "TASK_CONTEXT_MISMATCH": "integration",
    "MAP_REVISION_MISMATCH": "integration",
    "RESULT_DATA_INCOMPLETE": "integration",
    "VISION_CONFIDENCE_LOW": "perception",
    "VLM_PROPOSAL_REJECTED": "perception",
    "OPERATOR_CANCELLED": "operator",
    "SEGMENT_TIMEOUT": "navigation",
    "UNCLASSIFIED_RESULT": "unknown",
}


@dataclass(frozen=True)
class ClassifiedOutcome:
    primary_reason: str
    failure_domain: str
    contributing_reasons: tuple[str, ...]
    catalog_version: str = CATALOG_VERSION


class OutcomeClassifier:
    """Classify facts in catalog precedence order without I/O or global state."""

    _ordered_fact_keys = (
        "context_reason",
        "safety_reason",
        "cancellation_reason",
        "telemetry_reason",
        "navigation_reason",
        "criteria_reason",
        "timeout_reason",
    )

    def classify(self, facts: Mapping[str, object]) -> ClassifiedOutcome:
        reasons: list[str] = []
        if not facts.get("data_complete", False):
            reasons.append("RESULT_DATA_INCOMPLETE")
        if facts.get("context_matches") is False:
            reasons.append("TASK_CONTEXT_MISMATCH")
        if facts.get("map_revision_matches") is False:
            reasons.append("MAP_REVISION_MISMATCH")
        for key in self._ordered_fact_keys:
            reason = facts.get(key)
            if isinstance(reason, str) and reason:
                reasons.append(reason)

        reasons = list(dict.fromkeys(reasons))
        if reasons:
            primary = reasons[0]
        else:
            success = facts.get("success_reason")
            primary = success if isinstance(success, str) and success else "UNCLASSIFIED_RESULT"
        return ClassifiedOutcome(
            primary_reason=primary,
            failure_domain=REASON_DOMAINS.get(primary, "unknown"),
            contributing_reasons=tuple(reasons[1:]),
        )
