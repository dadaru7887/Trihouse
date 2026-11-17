"""제한된 복구 제안을 사람 없이 승인해도 되는지 판정하는 규칙.

목적: 예기치 못한 상황에서 로봇이 **스스로** 안전 대응·복구를 하게 한다. 사람이
항상 붙어 있을 수 없는 무인 구간이 그 대상이고, 사람은 예외에만 불려야 한다.

호출법: `recovery_routes` 가 제안을 저장한 직후 `classify()` 를 부르고, tier 가
자동이면 `repository.auto_decide_proposal()` 로 이어진다. 이 모듈은 판정만 하고
DB 도 로봇도 건드리지 않는다 — 그래야 규칙만 따로 테스트할 수 있다.

이 규칙이 안전을 책임지지 않는다는 점이 중요하다. 승인은 "이 제안을 시도해도
되는가" 이고, "이 동작이 물리적으로 안전한가" 는 실행 직전 경로 검사와 로봇의
admission check, 그리고 실행 내내 도는 20 Hz safety supervisor 가 답한다. 여기서
tier 를 잘못 매겨도 그 세 겹은 그대로 남는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


# 사람 확인 없이 실행해도 되는 skill.
#
# WAIT_REOBSERVE 는 움직이지 않으므로 되돌릴 것이 없다. BACKUP 은 방금 지나온
# 곳으로 짧게 물러나는 것이라 새 공간에 진입하지 않는다. REROUTE 는 가 본 적 없는
# 옆 공간으로 들어가므로 tier B 로 내려간다. REJOIN 은 절대 좌표를 Nav2 에 넘겨
# 이동 거리가 envelope 로 묶이지 않으므로 자동 대상이 아니다.
TIER_A_SKILLS = frozenset({"WAIT_REOBSERVE", "BACKUP"})
TIER_B_SKILLS = frozenset({"REROUTE_LEFT", "REROUTE_RIGHT"})

# tier A 로 자동 승인할 수 있는 최대 이동 거리.
#
# envelope 상한 0.25 m 의 절반보다 조금 넘는 값이다. 몸 길이(0.12 m) 정도의
# 이동이라 "한 걸음 물러난다" 를 넘지 않는다.
TIER_A_MAX_DISTANCE_M = 0.15

# VLM 이 스스로 밝힌 장면 확신도(state 의 scene_confidence, 1 = 확실)의 하한.
# 이보다 낮으면 상태 벡터 자체를 믿을 근거가 약하므로 자동 실행하지 않는다.
TIER_A_MIN_SCENE_CONFIDENCE = 0.6
TIER_B_MIN_SCENE_CONFIDENCE = 0.4

# 같은 episode 에서 이 횟수를 넘겨 시도했다면 규칙이 못 푸는 상황이다. 반복해서
# 같은 제안을 자동 승인하는 것은 해결이 아니라 무한 루프다.
MAX_AUTONOMOUS_ATTEMPTS = 3

AUTO_WORKER_ID = "SYS-RECOVERY-POLICY"


@dataclass(frozen=True)
class AutoDecision:
    """tier 와 그 근거. `approve` 가 False 면 사람이 판단해야 한다."""

    tier: str
    approve: bool
    reason: str
    notify: bool

    @property
    def requires_operator(self) -> bool:
        return not self.approve


def _distance_m(proposal: Mapping[str, Any]) -> float:
    action = proposal.get("canonical_action") or {}
    distance = action.get("distance_m")
    if isinstance(distance, (int, float)) and not isinstance(distance, bool):
        return abs(float(distance))
    coord = proposal.get("selected_coord") or (0.0, 0.0, 0.0)
    dx, dy = float(coord[0]), float(coord[1])
    return (dx * dx + dy * dy) ** 0.5


def _worst_observed_risk(proposal: Mapping[str, Any]) -> str:
    """제안에 실린 인지 근거 중 가장 높은 위험 등급.

    사람이 관련된 트리거는 등급과 무관하게 사람이 본다 — 쓰러진 작업자를 규칙이
    "낮은 위험" 으로 읽고 자동 실행하는 일이 있어서는 안 된다.
    """
    if proposal.get("trigger_type") == "person":
        return "critical"
    return "low"


def classify(
    proposal: Mapping[str, Any],
    *,
    attempt_no: int = 1,
    max_attempts: int = MAX_AUTONOMOUS_ATTEMPTS,
) -> AutoDecision:
    """이 제안을 자동 승인할 수 있는지 판정한다.

    판정은 보수적인 쪽으로만 틀린다: 조건을 하나라도 확인할 수 없으면 tier C 다.
    """
    skill = str(proposal.get("selected_skill_name", ""))
    state = proposal.get("state") or {}
    confidence = state.get("scene_confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return AutoDecision("C", False, "vlm scene confidence is unavailable", True)
    confidence = float(confidence)

    if attempt_no > max_attempts:
        return AutoDecision(
            "C", False,
            f"autonomous recovery exhausted after {max_attempts} attempts",
            True,
        )
    if _worst_observed_risk(proposal) == "critical":
        return AutoDecision("C", False, "person present in the trigger evidence", True)

    if skill in TIER_A_SKILLS:
        distance = _distance_m(proposal)
        if distance > TIER_A_MAX_DISTANCE_M:
            return AutoDecision(
                "C", False,
                f"retreat distance {distance:.2f} m exceeds the tier A bound",
                True,
            )
        if confidence < TIER_A_MIN_SCENE_CONFIDENCE:
            return AutoDecision(
                "C", False,
                f"vlm scene confidence {confidence:.2f} is below the tier A bound",
                True,
            )
        return AutoDecision(
            "A", True,
            f"{skill} within {TIER_A_MAX_DISTANCE_M} m, scene confidence {confidence:.2f}",
            False,
        )

    if skill in TIER_B_SKILLS:
        if confidence < TIER_B_MIN_SCENE_CONFIDENCE:
            return AutoDecision(
                "C", False,
                f"vlm scene confidence {confidence:.2f} is below the tier B bound",
                True,
            )
        return AutoDecision(
            "B", True,
            f"{skill} attempt {attempt_no}, scene confidence {confidence:.2f}",
            True,
        )

    return AutoDecision("C", False, f"{skill or 'unknown skill'} requires an operator", True)
