"""SR_03 RobotStatus를 1초 heartbeat와 상태 변경 시 발행하는 ROS 2 노드."""

from time import monotonic

import rclpy
from rclpy.node import Node

from nav_msgs.msg import Odometry                       # 주행거리 측정 패키지
from sensor_msgs.msg import BatteryState, LaserScan     # 배터리 잔량 반영, 라이다 데이터 수신 여부 확인

from trihouse_interfaces.msg import (
    BatteryCondition,
    BatteryPolicyState,
    CargoState,
    NavigationState,
    RobotStatus,
    SafetyState,
)

from .status import StatusInputs, build_status


class StatusNode(Node):
    """센서와 하위 상태를 모아 `/trihouse/status`로 발행하는 ROS 2 노드."""

    def __init__(self) -> None:
        """노드 상태, ROS 파라미터, 구독자, 발행자와 타이머를 초기화한다."""

        super().__init__('status_node')                     # 노드명

        self.declare_parameter('robot_id', 'PK-01')         # 로봇 식별자
        self.declare_parameter('sensor_timeout_s', 1.5)     # 센서 타임아웃(초)
        self.robot_id = self.get_parameter('robot_id').value
        self.timeout = float(self.get_parameter('sensor_timeout_s').value)

        # 각 센서 메시지를 마지막으로 받은 monotonic 시각; 초기 상태는 0.0 -> stale
        self.last_scan = self.last_odom = self.last_battery = 0.0
        self.odom: Odometry | None = None
        self.battery = 0.0

        # 작업 식별자
        self.job_id = ''
        self.step_id = ''

        # 초기 주행 상태
        self.navigation_state = NavigationState.STATE_IDLE      # 대기
        self.task_progress = 0.0                                # 작업 진행률

        self.safety = SafetyState()
        self.cargo = CargoState()
        self.battery_policy = BatteryPolicyState()

        self.create_subscription(LaserScan, '/scan', self._scan, 10)
        self.create_subscription(Odometry, '/odom', self._odom, 10)
        self.create_subscription(BatteryState, '/trihouse/battery', self._battery, 10)
        self.create_subscription(BatteryCondition, '/trihouse/battery/condition', self._battery_condition, 10)
        self.create_subscription(SafetyState, '/trihouse/safety/state', self._safety, 10)
        self.create_subscription(CargoState, '/trihouse/cargo/state', self._cargo, 10)
        self.create_subscription(BatteryPolicyState, '/trihouse/battery/policy_state', lambda m: setattr(self, 'battery_policy', m), 10)
        self.create_subscription(NavigationState, '/trihouse/navigation/state', self._navigation, 10)

        self.publisher = self.create_publisher(RobotStatus, '/trihouse/status', 10)

        self.create_timer(1.0, self._publish)   # heartbeat가 유지되도록 1초마다 _publish를 호출한다.

    def _scan(self, _: LaserScan) -> None:
        """라이다 데이터의 마지막 수신 시각을 기록한다."""

        # 메시지 내용은 사용하지 않으므로 인자 이름을 `_`로 표시한다.
        self.last_scan = monotonic()

    def _odom(self, message: Odometry) -> None:
        """최신 위치·속도와 odometry 수신 시각을 기록한다."""
        self.odom = message                                 # pose와 twist를 복사할 원본 메시지를 보관한다.
        self.last_odom = monotonic()

    def _battery(self, message: BatteryState) -> None:
        """최신 배터리 잔량과 배터리 메시지 수신 시각을 기록한다."""
        self.battery = message.percentage * 100.0           # BatteryState.percentage의 0.0~1.0 비율을 0.0~100.0 값으로 바꾼다.
        self.last_battery = monotonic()

    def _battery_condition(self, message: BatteryCondition) -> None:
        """최신 검증 관측값을 정책 snapshot의 입력 필드에 보존한다."""
        self.battery_policy.condition = message

    def _safety(self, message: SafetyState) -> None:
        """최신 안전 상태를 저장하고 통합 상태를 즉시 발행한다."""
        self.safety = message
        self._publish()

    def _cargo(self, message: CargoState) -> None:
        """최신 적재 상태를 저장하고 통합 상태를 즉시 발행한다."""
        self.cargo = message
        self._publish()

    def _navigation(self, message: NavigationState) -> None:
        """최신 작업 및 주행 상태를 저장하고 통합 상태를 즉시 발행한다."""
        # NavigationState에 포함된 현재 작업과 세부 단계 ID를 저장한다.
        self.job_id = message.job_id
        self.step_id = message.job_step_id

        # 주행 상태 상수와 작업 진행률을 저장한다.
        self.navigation_state = message.state
        self.task_progress = message.progress

        # 주행 상태 변경을 중앙 시스템이 바로 알 수 있도록 즉시 발행한다.
        self._publish()

    def _publish(self) -> None:
        """현재까지 수집한 값으로 RobotStatus를 조합해 발행한다."""

        self.publisher.publish(self._build_message())

    def _build_message(self) -> RobotStatus:
        """현재 저장된 입력을 하나의 RobotStatus 메시지로 조합한다."""

        # 모든 경과 시간 계산이 같은 기준 시각을 사용하도록 현재 시각을 한 번 읽는다.
        now = monotonic()

        # 각 센서가 timeout 이내에 들어왔는지를 정책 입력으로 전달한다.
        # build_status는 이 정보로 작업 할당 가능 여부와 오류 목록을 계산한다.
        summary = build_status(
            StatusInputs(
                self.robot_id,
                self.job_id,
                now - self.last_scan <= self.timeout,
                now - self.last_odom <= self.timeout,
                now - self.last_battery <= self.timeout,
            )
        )

        message = RobotStatus() # RobotStatus 메시지 타입의 인스턴스를 생성한다.

        # ROS clock의 현재 시각을 builtin_interfaces/Time 메시지로 변환한다.
        message.stamp = self.get_clock().now().to_msg()

        # 이 상태를 보낸 로봇과 현재 작업의 식별 정보를 채운다.
        message.robot_id = self.robot_id
        message.current_job_id = self.job_id
        message.current_job_step_id = self.step_id

        # 순수 상태 정책이 계산한 준비 여부와 오류 tuple을 ROS 배열로 복사한다.
        message.ready = summary.ready
        message.errors = list(summary.errors)

        # 센서에서 계산한 단순 배터리 잔량을 백분율 필드에 넣는다.
        message.battery_percentage = self.battery

        # 정책 노드에서 받은 BatteryPolicyState 메시지를 타입 그대로 포함한다.
        message.battery_policy = self.battery_policy

        # 하위 노드들에서 받은 적재 상태와 안전 상태 메시지를 그대로 포함한다.
        message.cargo = self.cargo
        message.safety = self.safety

        # 현재 주행 상태와 작업 진행률을 포함한다.
        message.navigation_state = self.navigation_state
        message.task_progress = self.task_progress

        # odometry를 한 번이라도 받았다면 위치, 속도, 기준 좌표계를 복사한다.
        if self.odom is not None:
            message.pose.pose = self.odom.pose.pose
            message.twist = self.odom.twist.twist
            message.frame_id = self.odom.header.frame_id

        return message


def main() -> None:
    rclpy.init()
    node = StatusNode()     # 상태 노드 생성

    try:
        rclpy.spin(node)    # 노드 실행
    finally:
        # 정상 종료와 예외 발생 모두에서 노드 자원과 rclpy context를 정리한다.
        node.destroy_node()
        rclpy.shutdown()
