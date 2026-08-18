"""시뮬 센서 주기와 안전 gate 의 신선도 판정이 맞아야 한다.

`safety_supervisor` 는 `sensor_timeout_s` 안에 센서가 오지 않으면 `sensor_timeout`
으로 STOP 을 건다. 그 STOP 이 `safety_blocked` → `dispatchable=False` 로 이어지고,
adapter 가 로봇을 RMF 에서 빼면 RMF 는 `Unable to replan assignments` 로 작업을
얹지 못한다.

2026-08-19 실측: `sim_hardware` 가 1 Hz 로 발행하는데 기본 timeout 이 0.5초라
55초 동안 상태 전이가 28회 일어났고 주문이 로봇에 얹히지 않았다. 실기 초음파는
훨씬 빨라 이 문제가 없다 — 시뮬 충실도의 문제다.
"""

from pathlib import Path


PINKY = Path(__file__).resolve().parents[1]
REPOSITORY = PINKY.parent
SIM_HARDWARE = (
    PINKY / "trihouse_pinky_bringup" / "trihouse_pinky_bringup" / "sim_hardware_node.py"
)
SIM_LAUNCH = (
    REPOSITORY
    / "trihouse_rmf_bridge"
    / "launch"
    / "two_pinky_order_demo.launch.py"
)


def test_sim_hardware_publish_period_is_tunable_and_fast_enough():
    """1 Hz 는 안전 gate 의 신선도 판정보다 느리다. 실기 초음파는 10 Hz 이상이다."""
    source = SIM_HARDWARE.read_text(encoding="utf-8")

    assert "'publish_period_s'" in source, "발행 주기가 고정값이라 맞출 수 없다"
    assert "create_timer(1.0" not in source, "여전히 1 Hz 로 고정돼 있다"


def test_sim_launch_gives_the_safety_gate_a_timeout_that_matches_sim_rates():
    """시뮬 센서 주기에 맞춘 신선도 상한을 명시해야 한다.

    안전 임계(정지·감속 거리)는 실기와 같게 두고 **신선도 판정만** 늦춘다.
    """
    source = SIM_LAUNCH.read_text(encoding="utf-8")
    supervisor = source.split('executable="safety_supervisor"')[1].split("),")[0]

    assert "sensor_timeout_s" in supervisor, "신선도 상한을 주지 않는다"
