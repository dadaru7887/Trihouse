"""일반 Nav2 도착과 OMX 인수인계 정차의 pose 허용오차를 구분하는 함수."""

from math import atan2, cos, hypot, sin


def within_tolerance(*, current: tuple[float, float, float], target: tuple[float, float, float], xy_tolerance_m: float, yaw_tolerance_rad: float) -> bool:
    """-pi/pi 경계의 yaw 불연속 없이 평면 pose 오차를 비교한다."""
    x, y, yaw = current; target_x, target_y, target_yaw = target
    yaw_error = atan2(sin(yaw - target_yaw), cos(yaw - target_yaw))
    return hypot(x - target_x, y - target_y) <= xy_tolerance_m and abs(yaw_error) <= yaw_tolerance_rad


def may_report_arrival(*, stationary: bool, waited_s: float, timeout_s: float) -> bool:
    """Nav2 성공 뒤 도착을 workflow 에 보고해도 되는 시점인지 판정한다.

    Nav2 `NavigateToPose` 는 goal tolerance 안에 들어오면 SUCCEEDED 를 주고 속도 0 을
    요구하지 않는다. `velocity_smoother` -> `collision_monitor` 체인 때문에 `cmd_vel` 은
    그 뒤에도 잠시 감쇠하므로, 결과가 온 순간 바로 보고하면 `TransportWorkflow` 가
    `"waiting for stop"` 을 돌려주고 phase 가 `NAVIGATING` 에 남는다. 다시 묻는 코드가
    없어서 그 상태가 영구히 남고 이후 모든 명령이 `"robot is not idle"` 로 거절된다.

    그래서 정차를 기다리되 무한히는 아니다. `timeout_s` 를 넘기면 보고한다 --
    끝내 멈추지 않는 것은 실제 결함이고, 그때는 goal 이 `ROBOT_NOT_STOPPED` 로
    정직하게 실패하는 편이 action 이 영원히 매달려 있는 것보다 낫다. 호출자는 그
    실패 뒤 `cancel_navigation()` 으로 로봇을 `IDLE` 로 되돌린다.
    """
    return bool(stationary) or waited_s >= timeout_s
