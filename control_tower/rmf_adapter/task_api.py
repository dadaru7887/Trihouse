"""Open-RMF Jazzy task API JSON과 Control Tower 상태 사이의 순수 경계."""

from dataclasses import dataclass
from typing import Any, Mapping

from .order_task import RmfAssignmentWindow, parse_assignment_window


@dataclass(frozen=True)
class GoToPlaceRequest:
    request_id: str
    job_step_id: int
    waypoint: str
    fleet_name: str
    robot_name: str
    request_time_ms: int
    # RMF 와 같은 시계로 읽은 "지금". 시뮬에서 fleet adapter 는 use_sim_time 으로
    # 돌아 기동 후 몇백 초짜리 시계를 쓴다. 원장의 벽시계 값을 시작 시각으로
    # 보내면 RMF 는 그 작업을 수십 년 뒤에나 시작할 수 있는 것으로 읽고, 입찰과
    # 배정은 되지만 로봇은 영원히 움직이지 않는다. 비워 두면 request_time_ms 를
    # 쓴다 — 실기는 두 시계가 같아서 그것으로 충분하다.
    earliest_start_time_ms: int | None = None
    requester: str = "trihouse_control_tower"

    def __post_init__(self) -> None:
        if not self.request_id.strip():
            raise ValueError("request_id is required")
        if self.job_step_id <= 0:
            raise ValueError("job_step_id must be positive")
        if not self.waypoint.strip():
            raise ValueError("waypoint is required")
        if not self.fleet_name.strip():
            raise ValueError("fleet_name is required")
        if not self.robot_name.strip():
            raise ValueError("robot_name is required")
        if self.request_time_ms < 0:
            raise ValueError("request_time_ms cannot be negative")
        if not self.requester.strip():
            raise ValueError("requester is required")


@dataclass(frozen=True)
class DispatchAcceptance:
    accepted: bool
    rmf_task_id: str = ""
    rmf_status: str = ""
    reason_code: str = ""
    detail: str = ""
    assignment: RmfAssignmentWindow | None = None


@dataclass(frozen=True)
class RmfTaskUpdate:
    task_id: str
    rmf_status: str
    step_state: str
    fleet_name: str
    robot_name: str
    observed_at_ms: int
    detail: str = ""
    planned_start_ms: int | None = None
    planned_end_ms: int | None = None


def build_dispatch_request(request: GoToPlaceRequest) -> dict[str, object]:
    """공식 compose/go_to_place 형식으로 이동 작업을 만든다.

    Control Tower가 Pinky를 최종 선택하므로 fleet과 robot을 모두 고정한다.
    RMF는 다른 Pinky로 대체 배정할 수 없다.
    """
    activity = {
        "category": "go_to_place",
        "description": {"one_of": [{"waypoint": request.waypoint}]},
    }
    return {
        "type": "dispatch_task_request",
        "request": {
            "category": "compose",
            "description": {
                "category": "go_to_place",
                "phases": [{"activity": activity}],
            },
            "unix_millis_request_time": request.request_time_ms,
            "unix_millis_earliest_start_time": (
                request.request_time_ms
                if request.earliest_start_time_ms is None
                else request.earliest_start_time_ms
            ),
            "requester": request.requester,
            "fleet_name": request.fleet_name,
            "robot_name": request.robot_name,
            "labels": [
                f"job_step:{request.job_step_id}",
                f"request:{request.request_id}",
                f"robot:{request.robot_name}",
            ],
        },
    }


def parse_dispatch_response(response: Mapping[str, Any]) -> DispatchAcceptance:
    """RMF 응답에서 성공 여부와 booking task ID만 추출한다."""
    if response.get("success") is not True:
        return DispatchAcceptance(
            False,
            reason_code="RMF_TASK_REJECTED",
            detail=_error_detail(response.get("errors")),
        )

    state = response.get("state")
    booking = state.get("booking") if isinstance(state, Mapping) else None
    task_id = booking.get("id") if isinstance(booking, Mapping) else None
    if not isinstance(task_id, str) or not task_id.strip():
        return DispatchAcceptance(False, reason_code="RMF_TASK_ID_MISSING")

    status = state.get("status", "")
    assignment: RmfAssignmentWindow | None = None
    try:
        assignment = parse_assignment_window(response)
    except ValueError:
        # Booking 수락과 robot/ETA 낙찰은 서로 다른 시점에 도착할 수 있다.
        # 후자는 assignment observer가 보완하므로 booking을 거절하지 않는다.
        pass
    return DispatchAcceptance(
        True,
        rmf_task_id=task_id,
        rmf_status=status if isinstance(status, str) else "",
        assignment=assignment,
    )


_TASK_STATES = {
    0: ("queued", "pending"),
    1: ("active", "running"),
    2: ("completed", "succeeded"),
    3: ("failed", "failed"),
    4: ("canceled", "cancelled"),
    5: ("pending", "pending"),
}


def normalize_task_summary(summary: Any, *, observed_at_ms: int) -> RmfTaskUpdate:
    """TaskSummary 숫자 상태를 DB와 관제용 안정 상태로 바꾼다."""
    task_id = str(getattr(summary, "task_id", "")).strip()
    if not task_id:
        profile = getattr(summary, "task_profile", None)
        task_id = str(getattr(profile, "task_id", "")).strip()
    if not task_id:
        raise ValueError("RMF task_id is required")
    if observed_at_ms < 0:
        raise ValueError("observed_at_ms cannot be negative")
    raw_state = int(getattr(summary, "state"))
    try:
        rmf_status, step_state = _TASK_STATES[raw_state]
    except KeyError as error:
        raise ValueError(f"unsupported RMF task state: {raw_state}") from error

    return RmfTaskUpdate(
        task_id=task_id,
        rmf_status=rmf_status,
        step_state=step_state,
        fleet_name=str(getattr(summary, "fleet_name", "")),
        robot_name=str(getattr(summary, "robot_name", "")),
        observed_at_ms=observed_at_ms,
        detail=str(getattr(summary, "status", "")),
        planned_start_ms=_ros_time_millis(
            getattr(summary, "start_time", None)
        ),
        planned_end_ms=_ros_time_millis(
            getattr(summary, "end_time", None)
        ),
    )



def normalize_fleet_state(
    state: Any, *, observed_at_ms: int
) -> tuple[RmfTaskUpdate, ...]:
    """`fleet_states` 에서 "어느 로봇이 어느 작업을 들고 있는가" 만 뽑는다.

    낙찰 결과가 원장으로 돌아오는 유일한 경로다. `task_summaries` 는 이 RMF
    배포에서 아무도 발행하지 않는다(2026-08-19 실측: 12초에 0건, 같은 시간
    `fleet_states` 는 97건). 워커는 제출 직후 응답을 받는데 그때는 입찰 전이라
    `assignment` 가 없는 것이 정상이고, 나중에 채워 주는 것이 이 경로다.

    **성패는 여기서 만들지 않는다.** `task_id` 가 빈 값으로 돌아가는 것은 완료와
    취소가 구분되지 않으므로 아무 사실도 아니다. 완료·실패는 로봇이 `task_event`
    로 직접 보고한다. 여기서 하는 일은 Gateway 가 outbox 를 닫을 수 있도록
    `robot_name` 을 돌려주는 것 하나다(`repositories.py` 의 `apply_rmf_task_update`
    가 `robot_name` 과 `message_state == 'sent'` 를 함께 볼 때 닫는다).

    작업을 든 채 잠깐 서 있는 것(`MODE_PAUSED`·`MODE_WAITING`)도 낙찰은 유효하므로
    mode 로 거르지 않는다. 거르면 로봇이 병목에서 대기하는 동안 배정이 사라진다.
    """
    if observed_at_ms < 0:
        raise ValueError("observed_at_ms cannot be negative")
    fleet_name = str(getattr(state, "name", ""))
    updates: list[RmfTaskUpdate] = []
    for robot in getattr(state, "robots", ()) or ():
        task_id = str(getattr(robot, "task_id", "")).strip()
        if not task_id:
            continue
        robot_name = str(getattr(robot, "name", "")).strip()
        if not robot_name:
            continue
        updates.append(
            RmfTaskUpdate(
                task_id=task_id,
                rmf_status="active",
                step_state="running",
                fleet_name=fleet_name,
                robot_name=robot_name,
                observed_at_ms=observed_at_ms,
                detail="fleet_states",
            )
        )
    return tuple(updates)



def _error_detail(errors: object) -> str:
    if not isinstance(errors, list):
        return ""
    details: list[str] = []
    for error in errors:
        if isinstance(error, Mapping):
            detail = error.get("detail") or error.get("category") or error.get("code")
            if detail is not None:
                details.append(str(detail))
        elif error is not None:
            details.append(str(error))
    return "; ".join(details)


def _ros_time_millis(stamp: object) -> int | None:
    if stamp is None:
        return None
    try:
        seconds = int(getattr(stamp, "sec"))
        nanoseconds = int(getattr(stamp, "nanosec"))
    except (AttributeError, TypeError, ValueError):
        return None
    if seconds < 0 or not 0 <= nanoseconds < 1_000_000_000:
        return None
    millis = seconds * 1_000 + nanoseconds // 1_000_000
    return millis if millis > 0 else None
