"""주문 route와 Open-RMF 낙찰 시간대 경계 테스트."""

import pytest

from control_tower.rmf_adapter.order_task import (
    OrderRouteRequest,
    RmfAssignmentWindow,
    build_order_dispatch_request,
    parse_assignment_window,
)


def test_multiple_waypoints_keep_order_but_are_not_live_ready() -> None:
    """OMX gate 없는 다중 route가 실주행 제출되는 회귀를 막는다."""
    request = OrderRouteRequest(
        "req-7",
        71,
        ("냉동1", "OMX1", "포장1"),
        "pinky_fleet",
        1_000,
    )

    payload = build_order_dispatch_request(request)

    phases = payload["request"]["description"]["phases"]
    assert [
        phase["activity"]["description"]["one_of"][0]["waypoint"]
        for phase in phases
    ] == ["냉동1", "OMX1", "포장1"]
    assert request.submission_ready is False


def test_single_waypoint_route_is_live_ready() -> None:
    """외부 action gate가 필요 없는 단일 이동이 불필요하게 차단되는 회귀를 막는다."""
    request = OrderRouteRequest(
        "req-8", 72, ("포장1",), "pinky_fleet", 2_000
    )

    assert request.submission_ready is True
    assert build_order_dispatch_request(request)["request"]["labels"] == [
        "job_step:72",
        "request:req-8",
        "submission_ready:true",
    ]


@pytest.mark.parametrize(
    "waypoints",
    [(), ("",), ("냉동1", "냉동1")],
)
def test_route_rejects_empty_or_duplicate_waypoints(
    waypoints: tuple[str, ...],
) -> None:
    """실행 의미가 없는 route가 RMF compose payload로 나가는 회귀를 막는다."""
    with pytest.raises(ValueError, match="waypoint"):
        OrderRouteRequest(
            "req-invalid", 73, waypoints, "pinky_fleet", 1_000
        )


def test_assignment_prefers_assigned_to_and_preserves_half_open_window() -> None:
    """낙찰 robot과 RMF 예상 시간대를 자체 계산값으로 바꾸는 회귀를 막는다."""
    window = parse_assignment_window(
        {
            "success": True,
            "state": {
                "booking": {"id": "task-1"},
                "assigned_to": {"group": "pinky_fleet", "name": "PK-01"},
                "dispatch": {
                    "assignment": {
                        "fleet_name": "wrong_fleet",
                        "expected_robot_name": "PK-99",
                    }
                },
                "unix_millis_start_time": 2_000,
                "unix_millis_finish_time": 8_000,
            },
        }
    )

    assert window == RmfAssignmentWindow(
        "task-1", "pinky_fleet", "PK-01", 2_000, 8_000
    )


def test_assignment_falls_back_to_dispatch_and_estimate() -> None:
    """assigned_to/finish가 아직 없는 초기 응답의 유효 낙찰값이 유실되는 회귀를 막는다."""
    window = parse_assignment_window(
        {
            "success": True,
            "state": {
                "booking": {
                    "id": "task-2",
                    "unix_millis_earliest_start_time": 3_000,
                },
                "dispatch": {
                    "assignment": {
                        "fleet_name": "pinky_fleet",
                        "expected_robot_name": "PK-02",
                    }
                },
                "estimate_millis": 4_000,
            },
        }
    )

    assert window == RmfAssignmentWindow(
        "task-2", "pinky_fleet", "PK-02", 3_000, 7_000
    )


def test_assignment_uses_verified_fallback_duration_only_when_needed() -> None:
    """RMF 종료 예상이 없을 때 임의의 0초 예약을 만드는 회귀를 막는다."""
    response = {
        "success": True,
        "state": {
            "booking": {
                "id": "task-3",
                "unix_millis_earliest_start_time": 4_000,
            },
            "assigned_to": {"group": "pinky_fleet", "name": "PK-01"},
        },
    }

    with pytest.raises(ValueError, match="finish"):
        parse_assignment_window(response)

    assert parse_assignment_window(
        response, fallback_duration_ms=5_000
    ).end_ms == 9_000


def test_assignment_rejects_missing_robot_and_reversed_window() -> None:
    """미등록 대상 또는 역전된 time-slot이 예약 repository로 넘어가는 회귀를 막는다."""
    with pytest.raises(ValueError, match="robot"):
        parse_assignment_window(
            {
                "success": True,
                "state": {
                    "booking": {"id": "task-4"},
                    "unix_millis_start_time": 1_000,
                    "unix_millis_finish_time": 2_000,
                },
            }
        )


def test_assignment_window_rejects_invalid_direct_construction() -> None:
    """TaskSummary 경로가 parser 검증을 우회해 역전 예약을 만드는 회귀를 막는다."""
    with pytest.raises(ValueError, match="end_ms"):
        RmfAssignmentWindow(
            "task-direct", "pinky_fleet", "PK-01", 5_000, 4_000
        )

    with pytest.raises(ValueError, match="finish"):
        parse_assignment_window(
            {
                "success": True,
                "state": {
                    "booking": {"id": "task-5"},
                    "assigned_to": {
                        "group": "pinky_fleet",
                        "name": "PK-01",
                    },
                    "unix_millis_start_time": 5_000,
                    "unix_millis_finish_time": 4_000,
                },
            }
        )
