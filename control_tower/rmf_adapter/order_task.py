"""주문 단위 Open-RMF composed task와 낙찰 시간대 경계."""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class OrderRouteRequest:
    request_id: str
    job_step_id: int
    waypoints: tuple[str, ...]
    fleet_name: str
    earliest_start_ms: int
    requester: str = "trihouse_control_tower"

    def __post_init__(self) -> None:
        if not self.request_id.strip():
            raise ValueError("request_id is required")
        if self.job_step_id <= 0:
            raise ValueError("job_step_id must be positive")
        if not self.waypoints:
            raise ValueError("at least one waypoint is required")
        normalized = tuple(waypoint.strip() for waypoint in self.waypoints)
        if any(not waypoint for waypoint in normalized):
            raise ValueError("waypoint cannot be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("waypoint cannot be duplicated in an order route")
        if not self.fleet_name.strip():
            raise ValueError("fleet_name is required")
        if self.earliest_start_ms < 0:
            raise ValueError("earliest_start_ms cannot be negative")
        if not self.requester.strip():
            raise ValueError("requester is required")
        object.__setattr__(self, "waypoints", normalized)

    @property
    def submission_ready(self) -> bool:
        """외부 OMX action gate가 없어도 안전하게 live 제출 가능한가."""
        return len(self.waypoints) == 1


@dataclass(frozen=True)
class RmfAssignmentWindow:
    task_id: str
    fleet_name: str
    robot_name: str
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id is required")
        if not self.fleet_name.strip() or not self.robot_name.strip():
            raise ValueError("fleet_name and robot_name are required")
        if self.start_ms < 0:
            raise ValueError("start_ms cannot be negative")
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be after start_ms")


def build_order_dispatch_request(
    request: OrderRouteRequest,
) -> dict[str, object]:
    """waypoint 순서를 보존한 공식 compose/go_to_place 요청을 만든다."""
    phases = [
        {
            "activity": {
                "category": "go_to_place",
                "description": {"one_of": [{"waypoint": waypoint}]},
            }
        }
        for waypoint in request.waypoints
    ]
    return {
        "type": "dispatch_task_request",
        "request": {
            "category": "compose",
            "description": {
                "category": "order_route",
                "phases": phases,
            },
            "unix_millis_request_time": request.earliest_start_ms,
            "unix_millis_earliest_start_time": request.earliest_start_ms,
            "requester": request.requester,
            "fleet_name": request.fleet_name,
            "labels": [
                f"job_step:{request.job_step_id}",
                f"request:{request.request_id}",
                f"submission_ready:{str(request.submission_ready).lower()}",
            ],
        },
    }


def parse_assignment_window(
    response: Mapping[str, Any],
    *,
    fallback_duration_ms: int | None = None,
) -> RmfAssignmentWindow:
    """RMF response의 낙찰 robot과 예상 반개방 시간 구간을 검증한다."""
    if response.get("success") is not True:
        raise ValueError("RMF task response was not successful")
    state = _mapping(response.get("state"))
    booking = _mapping(state.get("booking"))
    task_id = _required_text(booking.get("id"), "booking task_id")

    assigned_to = _mapping(state.get("assigned_to"))
    fleet_name = _optional_text(assigned_to.get("group"))
    robot_name = _optional_text(assigned_to.get("name"))
    if not fleet_name or not robot_name:
        dispatch = _mapping(state.get("dispatch"))
        assignment = _mapping(dispatch.get("assignment"))
        fleet_name = fleet_name or _optional_text(assignment.get("fleet_name"))
        robot_name = robot_name or _optional_text(
            assignment.get("expected_robot_name")
        )
    if not fleet_name or not robot_name:
        raise ValueError("RMF assignment robot is required")

    start_value = state.get("unix_millis_start_time")
    if start_value is None:
        start_value = booking.get("unix_millis_earliest_start_time")
    start_ms = _non_negative_millis(start_value, "start")

    finish_value = state.get("unix_millis_finish_time")
    if finish_value is None:
        duration_value = state.get("estimate_millis")
        if duration_value is None:
            duration_value = fallback_duration_ms
        duration_ms = _positive_millis(duration_value, "finish duration")
        end_ms = start_ms + duration_ms
    else:
        end_ms = _non_negative_millis(finish_value, "finish")
    if end_ms <= start_ms:
        raise ValueError("finish time must be after start time")

    return RmfAssignmentWindow(
        task_id=task_id,
        fleet_name=fleet_name,
        robot_name=robot_name,
        start_ms=start_ms,
        end_ms=end_ms,
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _required_text(value: object, field: str) -> str:
    text = _optional_text(value)
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _optional_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _non_negative_millis(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} time must be a non-negative integer")
    return value


def _positive_millis(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value
