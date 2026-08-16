"""구조화된 실행 사실을 버전이 있는 결과 원인으로 결정적으로 분류한다."""

from dataclasses import dataclass
from typing import Mapping


CATALOG_VERSION = "v1"

# 외부에서 안정적으로 집계할 원인 코드와 담당 장애 영역의 매핑이다.
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
    """대표 원인과 부가 원인을 순서까지 보존한 불변 분류 결과."""
    primary_reason: str
    failure_domain: str
    contributing_reasons: tuple[str, ...]
    catalog_version: str = CATALOG_VERSION


class OutcomeClassifier:
    """I/O나 전역 상태 없이 카탈로그 우선순위대로 실행 사실을 분류한다."""

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
        """데이터/문맥 무결성을 우선하고 그 뒤 도메인별 원인을 선택한다."""
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

        # 같은 코드가 여러 fact에 있어도 최초 우선순위만 유지한다.
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
