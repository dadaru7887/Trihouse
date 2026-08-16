"""Control Tower와 Open-RMF task API 사이의 순수 JSON 계약 테스트."""

from dataclasses import dataclass

import pytest

from control_tower.rmf_adapter.task_api import (
    GoToPlaceRequest,
    build_dispatch_request,
    normalize_task_summary,
    parse_dispatch_response,
)


def test_builds_official_compose_go_to_place_payload() -> None:
    """목적지 필드가 틀려 RMF가 작업을 거절하는 회귀를 막는다."""
    payload = build_dispatch_request(
        GoToPlaceRequest(
            request_id="req-1",
            job_step_id=42,
            waypoint="대기1",
            fleet_name="pinky_fleet",
            robot_name="PK_01",
            request_time_ms=1_000,
        )
    )

    assert payload == {
        "type": "dispatch_task_request",
        "request": {
            "category": "compose",
            "description": {
                "category": "go_to_place",
                "phases": [
                    {
                        "activity": {
                            "category": "go_to_place",
                            "description": {
                                "one_of": [{"waypoint": "대기1"}]
                            },
                        }
                    }
                ],
            },
            "unix_millis_request_time": 1_000,
            "unix_millis_earliest_start_time": 1_000,
            "requester": "trihouse_control_tower",
            "fleet_name": "pinky_fleet",
            "robot_name": "PK_01",
            "labels": ["job_step:42", "request:req-1", "robot:PK_01"],
        },
    }


@pytest.mark.parametrize("waypoint", ["", "   "])
def test_request_rejects_an_empty_waypoint(waypoint: str) -> None:
    """등록되지 않은 빈 목적지가 RMF 요청으로 나가는 회귀를 막는다."""
    with pytest.raises(ValueError, match="waypoint"):
        GoToPlaceRequest("req-1", 42, waypoint, "pinky_fleet", "PK_01", 1_000)


def test_success_response_uses_booking_id_only() -> None:
    """응답의 다른 ID를 RMF task ID로 오인하는 회귀를 막는다."""
    accepted = parse_dispatch_response(
        {
            "success": True,
            "state": {
                "booking": {"id": "rmf-task-1"},
                "status": "queued",
                "active": 17,
            },
        }
    )

    assert accepted.accepted is True
    assert accepted.rmf_task_id == "rmf-task-1"
    assert accepted.rmf_status == "queued"
    assert accepted.assignment is None


def test_success_response_exposes_complete_assignment_window() -> None:
    """RMF 낙찰 robot/ETA가 outbox ack 과정에서 유실되는 회귀를 막는다."""
    accepted = parse_dispatch_response(
        {
            "success": True,
            "state": {
                "booking": {"id": "rmf-task-2"},
                "status": "queued",
                "assigned_to": {
                    "group": "pinky_fleet",
                    "name": "PK-01",
                },
                "unix_millis_start_time": 3_000,
                "unix_millis_finish_time": 9_000,
            },
        }
    )

    assert accepted.accepted is True
    assert accepted.assignment is not None
    assert accepted.assignment.task_id == "rmf-task-2"
    assert accepted.assignment.robot_name == "PK-01"
    assert accepted.assignment.start_ms == 3_000
    assert accepted.assignment.end_ms == 9_000


def test_success_response_without_booking_id_is_rejected() -> None:
    """task ID 없는 성공 응답이 DB step을 running으로 만드는 회귀를 막는다."""
    accepted = parse_dispatch_response(
        {"success": True, "state": {"status": "queued"}}
    )

    assert accepted.accepted is False
    assert accepted.reason_code == "RMF_TASK_ID_MISSING"


@dataclass(frozen=True)
class Summary:
    fleet_name: str
    task_id: str
    state: int
    robot_name: str
    status: str = ""


@pytest.mark.parametrize(
    ("rmf_state", "rmf_status", "step_state"),
    [
        (0, "queued", "pending"),
        (1, "active", "running"),
        (2, "completed", "succeeded"),
        (3, "failed", "failed"),
        (4, "canceled", "cancelled"),
        (5, "pending", "pending"),
    ],
)
def test_normalizes_task_summary_states(
    rmf_state: int, rmf_status: str, step_state: str
) -> None:
    """RMF 숫자 상태와 DB 상태가 서로 다른 의미로 저장되는 회귀를 막는다."""
    update = normalize_task_summary(
        Summary("pinky_fleet", "rmf-task-1", rmf_state, "PK-01"),
        observed_at_ms=2_000,
    )

    assert update.task_id == "rmf-task-1"
    assert update.rmf_status == rmf_status
    assert update.step_state == step_state
    assert update.fleet_name == "pinky_fleet"
    assert update.robot_name == "PK-01"
    assert update.observed_at_ms == 2_000


def test_unknown_task_summary_state_is_rejected() -> None:
    """새로운 미지원 RMF 상태를 성공이나 실패로 추정하는 회귀를 막는다."""
    with pytest.raises(ValueError, match="unsupported RMF task state"):
        normalize_task_summary(
            Summary("pinky_fleet", "rmf-task-1", 99, "PK-01"),
            observed_at_ms=2_000,
        )


def test_task_summary_falls_back_to_profile_task_id() -> None:
    """optional top-level task_id가 비어 read model update가 유실되는 회귀를 막는다."""
    class Profile:
        task_id = "rmf-task-profile"

    class ProfileOnlySummary:
        fleet_name = "pinky_fleet"
        task_id = ""
        task_profile = Profile()
        state = 1
        robot_name = "PK-01"
        status = ""

    update = normalize_task_summary(
        ProfileOnlySummary(), observed_at_ms=2_000
    )

    assert update.task_id == "rmf-task-profile"


def test_task_summary_exposes_assignment_time_window() -> None:
    """초기 API 응답에 ETA가 없을 때 summary의 예약 시간이 유실되는 회귀를 막는다."""
    class Stamp:
        def __init__(self, sec: int, nanosec: int = 0) -> None:
            self.sec = sec
            self.nanosec = nanosec

    class TimedSummary(Summary):
        start_time = Stamp(2, 500_000_000)
        end_time = Stamp(8)

    update = normalize_task_summary(
        TimedSummary("pinky_fleet", "rmf-task-1", 0, "PK-01"),
        observed_at_ms=1_000,
    )

    assert update.planned_start_ms == 2_500
    assert update.planned_end_ms == 8_000
