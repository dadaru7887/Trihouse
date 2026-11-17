"""사람 없이 실행해도 되는 복구 제안을 가르는 규칙."""

from fms_gateway.app.recovery_autoapproval import (
    MAX_AUTONOMOUS_ATTEMPTS,
    classify,
)


def proposal(**overrides) -> dict:
    values = {
        "trigger_type": "blocked",
        "selected_skill_name": "WAIT_REOBSERVE",
        "selected_coord": [0.0, 0.0, 0.0],
        "canonical_action": {"distance_m": 0.0, "action_family": "wait"},
        "state": {"scene_confidence": 0.8},
        "step_no": 1,
    }
    values.update(overrides)
    return values


def test_waiting_in_place_needs_nobody() -> None:
    """움직이지 않는 행동에는 되돌릴 것이 없다."""
    verdict = classify(proposal())

    assert verdict.tier == "A"
    assert verdict.approve is True
    assert verdict.notify is False


def test_short_backup_is_autonomous_but_a_long_one_is_not() -> None:
    """방금 지나온 곳으로 물러나는 것과 새 공간으로 들어가는 것은 다르다."""
    short = classify(proposal(
        selected_skill_name="BACKUP",
        canonical_action={"distance_m": 0.10, "action_family": "retreat"},
    ))
    far = classify(proposal(
        selected_skill_name="BACKUP",
        canonical_action={"distance_m": 0.24, "action_family": "retreat"},
    ))

    assert short.tier == "A"
    assert far.requires_operator is True


def test_detour_runs_autonomously_but_tells_the_control_tower() -> None:
    """우회는 가 본 적 없는 옆 공간으로 들어가므로 관제가 알아야 한다."""
    verdict = classify(proposal(
        selected_skill_name="REROUTE_LEFT",
        canonical_action={"distance_m": 0.2, "action_family": "detour"},
    ))

    assert verdict.tier == "B"
    assert verdict.approve is True
    assert verdict.notify is True


def test_a_person_in_the_evidence_always_goes_to_a_human() -> None:
    """쓰러진 작업자를 규칙이 낮은 위험으로 읽고 자동 실행해서는 안 된다."""
    verdict = classify(proposal(trigger_type="person"))

    assert verdict.requires_operator is True
    assert verdict.notify is True


def test_repeated_failure_stops_being_the_policy_s_problem() -> None:
    """같은 제안을 반복 자동 승인하는 것은 해결이 아니라 무한 루프다."""
    verdict = classify(
        proposal(selected_skill_name="BACKUP",
                 canonical_action={"distance_m": 0.1, "action_family": "retreat"}),
        attempt_no=MAX_AUTONOMOUS_ATTEMPTS + 1,
    )

    assert verdict.requires_operator is True
    assert "attempts" in verdict.reason


def test_an_uncertain_reading_is_not_acted_on_alone() -> None:
    """상태 벡터를 믿을 근거가 약하면 그 위의 판단도 믿을 수 없다.

    scene_confidence 는 1 이 확실이다. 낮은 값이 사람에게 가야 한다.
    """
    assert classify(proposal(state={"scene_confidence": 0.15})).requires_operator is True
    assert classify(proposal(state={"scene_confidence": 0.95})).approve is True


def test_a_missing_scene_confidence_is_not_read_as_confident() -> None:
    """확인할 수 없는 조건은 통과가 아니라 거부다."""
    assert classify(proposal(state={})).requires_operator is True


def test_rejoin_is_never_autonomous() -> None:
    """REJOIN 만 절대 좌표를 Nav2 에 넘겨 이동 거리가 envelope 로 묶이지 않는다."""
    verdict = classify(proposal(
        selected_skill_name="REJOIN",
        canonical_action={"action_family": "rejoin"},
    ))

    assert verdict.tier == "C"
    assert verdict.requires_operator is True
