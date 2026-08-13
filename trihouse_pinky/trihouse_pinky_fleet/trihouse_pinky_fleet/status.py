"""센서 최신 여부를 이용해 로봇의 준비 상태를 판단하는 순수 정책 모듈.

이 파일은 ROS 토픽을 직접 구독하거나 메시지를 발행하지 않는다.
ROS 통신은 ``status_node.py``가 담당하고, 이 모듈은 전달받은 값만으로
로봇이 새 작업을 받을 수 있는 상태인지와 어떤 오류가 있는지를 계산한다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StatusInputs:
    """상태 정책이 판단에 사용할 입력값을 하나로 묶은 불변 데이터 객체.

    status_node.py가 각 센서의 마지막 수신 시각을 검사한 뒤,
    현재 시각 기준으로 데이터가 최신이면 True, 오래됐으면 False를
    각 *_fresh 필드에 넣어 이 객체를 생성한다.

    frozen=True이므로 객체가 생성된 뒤에는 필드 값을 변경할 수 없다.
    """

    robot_id: str               # 로봇 고유 식별자

    scan_fresh: bool = True     # 라이다 스캔 메시지 수신 여부
    odom_fresh: bool = True     # odometry 메시지 수신 여부
    battery_fresh: bool = True  # 배터리 상태 메시지 수신 여부
    map_pose_fresh: bool = True
    nav_available: bool = True
    control_link_online: bool = True
    safety_clear: bool = True
    battery_dispatchable: bool = True
    maintenance_clear: bool = True
    cargo_allows_dispatch: bool = True


@dataclass(frozen=True)
class StatusSummary:
    """상태 정책의 판단 결과를 하나로 묶은 불변 데이터 객체.

    build_status()가 StatusInputs를 검사한 뒤 생성하며,
    status_node.py는 이 결과의 ready와 errors를
    최종 RobotStatus ROS 메시지에 복사한다.
    """

    robot_id: str
    telemetry_valid: bool
    execution_ready: bool
    dispatchable: bool
    ready: bool                 # 하위 호환 alias이며 dispatchable과 항상 같다.

    errors: tuple[str, ...]     # 오래된 센서에 대응하는 오류 이름들을 순서대로 담는다.


def build_status(inputs: StatusInputs) -> StatusSummary:
    """센서 최신 여부를 검사해 로봇의 준비 상태와 오류 목록을 반환한다.

    Args:
        inputs: 로봇·작업 식별자와 scan, odom, battery 최신 여부를 담은 값.

    Returns:
        하나라도 오래된 센서가 있으면 ready=False와 해당 stale 오류를,
        모든 센서가 최신이면 ready=True와 빈 오류 tuple을 담은 결과.
    """

    # 센서별 오류 이름과 최신 여부를 한 쌍으로 묶어 차례대로 검사한다.
    # fresh가 False인 센서의 오류 이름만 tuple에 포함된다.
    sensor_errors = tuple(
        name for name, fresh in (
            ("scan_stale", inputs.scan_fresh),
            ("odom_stale", inputs.odom_fresh),
            ("battery_stale", inputs.battery_fresh),
            ("map_pose_stale", inputs.map_pose_fresh),
        ) if not fresh
    )
    execution_errors = tuple(
        name for name, allowed in (
            ("nav_unavailable", inputs.nav_available),
            ("control_link_offline", inputs.control_link_online),
            ("safety_blocked", inputs.safety_clear),
        ) if not allowed
    )
    dispatch_errors = tuple(
        name for name, allowed in (
            ("battery_not_dispatchable", inputs.battery_dispatchable),
            ("maintenance_blocked", inputs.maintenance_clear),
            ("cargo_blocks_dispatch", inputs.cargo_allows_dispatch),
        ) if not allowed
    )
    telemetry_valid = not sensor_errors
    execution_ready = telemetry_valid and not execution_errors
    dispatchable = execution_ready and not dispatch_errors
    errors = sensor_errors + execution_errors + dispatch_errors
    return StatusSummary(
        inputs.robot_id,
        telemetry_valid,
        execution_ready,
        dispatchable,
        dispatchable,
        errors,
    )
