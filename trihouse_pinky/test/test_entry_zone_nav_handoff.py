"""Nav2가 entry zone에서 규칙 제어로 제어권을 넘기는 실행 계약."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml


PINKY = Path(__file__).resolve().parents[1]
REPOSITORY = PINKY.parent
sys.path.insert(0, str(PINKY / "trihouse_pinky_docking"))
sys.path.insert(0, str(PINKY / "trihouse_pinky_fleet"))

rclpy_task = pytest.importorskip("rclpy.task", reason="rclpy가 필요하다")
fleet_node = pytest.importorskip("trihouse_pinky_fleet.fleet_node")

from trihouse_pinky_docking.narrow_zone import load_narrow_zones  # noqa: E402


Future = rclpy_task.Future
PROFILE_FILE = REPOSITORY / "config" / "narrow_zones.new_map_2.yaml"


class _Logger:
    def info(self, message: str) -> None:
        pass


class _CancelResponse:
    goals_canceling = (object(),)


class _NavResult:
    status = 5


class _NavHandle:
    def __init__(self) -> None:
        self.result = Future()
        self.cancel_requests = 0

    def get_result_async(self) -> Future:
        return self.result

    def cancel_goal_async(self) -> Future:
        self.cancel_requests += 1
        canceled = Future()
        canceled.set_result(_CancelResponse())
        self.result.set_result(_NavResult())
        return canceled


class _GoalHandle:
    is_cancel_requested = False


class _Node:
    def __init__(self) -> None:
        self.map_pose = (1.10, -1.19, -2.0)

    def get_logger(self) -> _Logger:
        return _Logger()

    def _sleep(self, seconds: float) -> Future:
        completed = Future()
        completed.set_result(None)
        return completed


def _profile():
    document = yaml.safe_load(PROFILE_FILE.read_text(encoding="utf-8"))
    return load_narrow_zones(document, map_name="new_map_2")[
        "frozen_storage_loading_dock_01"
    ]


def _drive(coroutine, *, max_steps: int = 20):
    for _ in range(max_steps):
        try:
            yielded = coroutine.send(None)
        except StopIteration as stopped:
            return stopped.value
        if isinstance(yielded, Future):
            if not yielded.done():
                raise AssertionError("테스트 경계의 Future가 완료되지 않았다")
            continue
        if yielded is None:
            continue
        raise TypeError(f"rclpy executor가 받을 수 없는 값: {type(yielded)}")
    raise AssertionError("entry zone handoff가 끝나지 않았다")


def test_entering_entry_zone_cancels_nav2_and_reports_rule_handoff() -> None:
    """zone 진입을 무시하고 Nav2 최종 yaw까지 기다리는 결함을 잡는다."""
    node = _Node()
    handle = _NavHandle()

    outcome = _drive(
        fleet_node.FleetNode._await_nav_or_entry_handoff(
            node, handle, _GoalHandle(), _profile()
        )
    )

    assert outcome.handed_off is True
    assert outcome.error == ""
    assert handle.cancel_requests == 1
