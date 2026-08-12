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
