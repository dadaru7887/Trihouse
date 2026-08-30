"""관측을 얼마나 자주 올리는가.

추론은 10~15 Hz 로 돌지만 관측이 로봇에 닿는 길은 TCP 8788 이고 **주행 명령이
같은 링크를 쓴다.** 그대로 흘리면 `execute_transport` 가 뒤로 밀린다.
"""

import pytest

from vision_ai.robot.perception.reporting import ReportPolicy, ReportThrottle


def test_a_state_change_is_always_reported() -> None:
    """사람이 나타나거나 낙상 상태가 넘어간 것은 기다릴 이유가 없다."""
    throttle = ReportThrottle(ReportPolicy(ttl_ms=600))
    assert throttle.should_report(0.0, "PERSON:NORMAL")
    assert throttle.should_report(0.05, "PERSON:FALL_SUSPECTED")
    assert throttle.should_report(0.10, "NO_DETECTION")


def test_an_unchanged_state_is_not_reported_every_frame() -> None:
    """15 Hz 를 그대로 올리면 링크가 관측으로 찬다."""
    throttle = ReportThrottle(ReportPolicy(ttl_ms=600))
    assert throttle.should_report(0.0, "PERSON:NORMAL")
    for frame in range(1, 4):
        assert not throttle.should_report(frame * 0.066, "PERSON:NORMAL")


def test_an_unchanged_state_is_refreshed_before_it_expires() -> None:
    """갱신을 멈추면 안전 gate 가 사람을 잊고 로봇이 다시 빨라진다."""
    policy = ReportPolicy(ttl_ms=600)
    throttle = ReportThrottle(policy)
    throttle.should_report(0.0, "PERSON:NORMAL")
    assert not throttle.should_report(policy.refresh_interval_s - 0.01, "PERSON:NORMAL")
    assert throttle.should_report(policy.refresh_interval_s, "PERSON:NORMAL")


def test_the_refresh_beats_expiry_twice_over() -> None:
    """수명의 절반으로 보낸다 — 한 번 유실돼도 다음 갱신이 만료 전에 닿는다."""
    policy = ReportPolicy(ttl_ms=600)
    assert policy.refresh_interval_s == pytest.approx(0.3)
    assert 2 * policy.refresh_interval_s <= policy.ttl_ms / 1000.0


def test_the_reported_rate_stays_far_below_the_inference_rate() -> None:
    """15 Hz 추론에서 실제 전송이 몇 배 줄어드는지 센다."""
    throttle = ReportThrottle(ReportPolicy(ttl_ms=600))
    sent = sum(1 for frame in range(150) if throttle.should_report(frame / 15.0, "PERSON:NORMAL"))
    assert sent <= 35, f"10 초 동안 {sent} 건은 너무 잦다"


def test_a_zero_lifetime_is_refused() -> None:
    """수명이 0 이면 관측이 도착하자마자 만료된다."""
    with pytest.raises(ValueError):
        ReportPolicy(ttl_ms=0)
