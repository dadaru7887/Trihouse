"""Gazebo OMX mock과 공용 CargoState 상수 계약."""

from trihouse_interfaces.msg import CargoState

from trihouse_omx_adapter.gazebo_adapter_node import (
    cargo_state_for_confirmation,
)


def test_unconfirmed_mock_reports_unlocked_cargo() -> None:
    """존재하지 않는 EMPTY 상수 때문에 OMX mock node가 종료되는 회귀를 막는다."""
    assert cargo_state_for_confirmation(False) == CargoState.STATE_UNLOCKED


def test_confirmed_mock_reports_locked_cargo() -> None:
    """적재 확인 뒤 cargo lock 상태가 유실되는 회귀를 막는다."""
    assert cargo_state_for_confirmation(True) == CargoState.STATE_LOCKED
