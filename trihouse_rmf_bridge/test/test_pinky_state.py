import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trihouse_rmf_bridge.state import PinkyState


def test_valid_state_exposes_rmf_pose_and_soc() -> None:
    state = PinkyState("PK-01", "L1", 1.0, 2.0, 0.5, 75.0, True, 10)

    validation = state.validate(now_ns=20, timeout_ns=20)

    assert validation.accepted
    assert validation.reason_code == "OK"
    assert state.rmf_position == (1.0, 2.0, 0.5)
    assert state.rmf_soc == 0.75


def test_stale_state_is_rejected() -> None:
    state = PinkyState("PK-01", "L1", 0.0, 0.0, 0.0, 50.0, True, 0)

    validation = state.validate(now_ns=100, timeout_ns=10)

    assert not validation.accepted
    assert validation.reason_code == "PINKY_STATUS_STALE"


def test_invalid_pose_is_rejected() -> None:
    state = PinkyState("PK-01", "L1", math.nan, 0.0, 0.0, 50.0, True, 100)

    validation = state.validate(now_ns=100, timeout_ns=10)

    assert not validation.accepted
    assert validation.reason_code == "PINKY_POSE_INVALID"


def test_invalid_battery_is_rejected() -> None:
    state = PinkyState("PK-01", "L1", 0.0, 0.0, 0.0, 101.0, True, 100)

    validation = state.validate(now_ns=100, timeout_ns=10)

    assert not validation.accepted
    assert validation.reason_code == "PINKY_BATTERY_INVALID"


def test_unready_state_is_rejected() -> None:
    state = PinkyState("PK-01", "L1", 0.0, 0.0, 0.0, 50.0, False, 100)

    validation = state.validate(now_ns=100, timeout_ns=10)

    assert not validation.accepted
    assert validation.reason_code == "PINKY_NOT_READY"


def test_a_robot_that_is_executing_keeps_reporting_while_safety_blocks_it() -> None:
    """수행 중에는 dispatchable 이 떨어져도 RMF 갱신을 멈추지 않는다.

    협로에 들어가면 통로 벽이 stop_distance_m(0.30 m) 안에 들어와 안전 gate 가
    STOP 을 건다. 그러면 `safety_blocked` 로 dispatchable 이 false 가 되는데,
    그것을 이유로 갱신을 끊으면 RMF 가 명령 핸들을 "응답 없음" 으로 보고
    작업을 취소한다(MoveRobot.hpp:170). 2026-08-20 시뮬에서 2회 재현했다.

    dispatchable 은 "**새 작업**을 줘도 되는가" 이지 "하던 일을 계속해도
    되는가" 가 아니다.
    """
    state = PinkyState("PK-01", "L1", 1.0, 2.0, 0.5, 60.0, False, 100)

    validation = state.validate(now_ns=100, timeout_ns=10, executing=True)

    assert validation.accepted
    assert validation.reason_code == "OK"


def test_an_idle_robot_that_is_not_dispatchable_is_still_rejected() -> None:
    """놀고 있을 때는 그대로 거절한다. RMF 가 새 작업을 주면 안 된다."""
    state = PinkyState("PK-01", "L1", 1.0, 2.0, 0.5, 60.0, False, 100)

    validation = state.validate(now_ns=100, timeout_ns=10, executing=False)

    assert not validation.accepted
    assert validation.reason_code == "PINKY_NOT_READY"


def test_telemetry_failures_reject_even_while_executing() -> None:
    """pose 를 믿을 수 없으면 수행 중이라도 RMF 에 넘기지 않는다.

    이건 안전 판정이 아니라 **좌표가 거짓인 경우**다. 틀린 자리를 계속 보고하면
    RMF 의 교통 계획이 그 거짓 위에 쌓인다.
    """
    stale = PinkyState("PK-01", "L1", 1.0, 2.0, 0.5, 60.0, True, 0)
    assert stale.validate(now_ns=100, timeout_ns=10, executing=True).reason_code == "PINKY_STATUS_STALE"

    bad_pose = PinkyState("PK-01", "L1", math.nan, 2.0, 0.5, 60.0, True, 100)
    assert bad_pose.validate(now_ns=100, timeout_ns=10, executing=True).reason_code == "PINKY_POSE_INVALID"

    bad_battery = PinkyState("PK-01", "L1", 1.0, 2.0, 0.5, 101.0, True, 100)
    assert bad_battery.validate(now_ns=100, timeout_ns=10, executing=True).reason_code == "PINKY_BATTERY_INVALID"
