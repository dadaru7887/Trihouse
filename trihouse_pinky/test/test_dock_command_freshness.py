"""도킹 action 종료 뒤의 오래된 zero Twist가 Nav2를 막지 않는 정책."""

import sys
from pathlib import Path

PINKY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PINKY / "trihouse_pinky_safety"))

from trihouse_pinky_safety.policy import MotionCommand, select_motion_source  # noqa: E402


def test_stale_dock_stop_falls_back_to_fresh_nav_command() -> None:
    nav = MotionCommand(0.10, 0.0)
    dock = MotionCommand(0.0, 0.0)
    assert select_motion_source(
        nav, dock, now_s=10.26, dock_received_at_s=10.0, dock_timeout_s=0.25
    ) == nav


def test_fresh_dock_command_has_priority_over_nav_command() -> None:
    nav = MotionCommand(0.10, 0.0)
    dock = MotionCommand(-0.05, 0.2)
    assert select_motion_source(
        nav, dock, now_s=10.24, dock_received_at_s=10.0, dock_timeout_s=0.25
    ) == dock
