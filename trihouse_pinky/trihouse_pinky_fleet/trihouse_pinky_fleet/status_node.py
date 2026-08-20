"""SR_03 RobotStatus를 1초 heartbeat와 상태 변경 시 발행하는 ROS 2 노드."""

import rclpy
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)
from rclpy.node import Node
from rclpy.time import Time

import tf2_ros

from nav_msgs.msg import Odometry                       # 주행거리 측정 패키지
from sensor_msgs.msg import BatteryState, LaserScan     # 배터리 잔량 반영, 라이다 데이터 수신 여부 확인

from trihouse_interfaces.msg import (
    BatteryCondition,
    BatteryPolicyState,
    CargoState,
    ConnectionState,
    NavigationState,
    Readiness,
    RobotStatus,
    SafetyState,
    TaskContext,
)

from .status import StatusInputs, build_status



# `trihouse/fms/state` 는 흘러가는 사건이 아니라 최신 값이 계속 유효한 사실이다.
# `gateway_node` 는 연결 상태가 **바뀔 때만** 발행하므로, 늦게 뜬 구독자가 그 한
# 번을 놓치면 영원히 모른다. 그러면 TCP 는 붙어 있는데 로봇이
# `control_link_offline` 로 굳어 RMF 가 받아 주지 않는다. 발행·구독 양쪽을 함께
# 바꿔야 한다 — 한쪽만 바꾸면 QoS 가 맞지 않아 아예 연결되지 않는다.
CONNECTION_STATE_QOS = QoSProfile(
    depth=1,
    history=QoSHistoryPolicy.KEEP_LAST,
    reliability=QoSReliabilityPolicy.RELIABLE,
    durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
)

def safety_allows_work(safety_state: int) -> bool:
    """SLOW 에서도 작업을 받는가. 받는다.

    SLOW 는 **속도 제한**이지 차단이 아니다. `apply_safety_gate` 도 SLOW 에서
    `goal_may_continue=True` 로 진행을 허용한다 — 진행 중 주행은 되는데 새 배정만
    막으면 두 판정이 어긋난다.

    이것을 `STATE_CLEAR` 하나로 두면 사람이 근처에 있는 동안 로봇이 새 일을 아예
    받지 못한다. 사람이 지나갈 때마다 작업이 멈추는 것은 안전이 아니라 가용성
    손실이고, 실제 보호는 속도 제한과 STOP 이 한다.
    """
    return safety_state in (SafetyState.STATE_CLEAR, SafetyState.STATE_SLOW)


class StatusNode(Node):
    """센서와 하위 상태를 모아 `/trihouse/status`로 발행하는 ROS 2 노드."""

    def __init__(self) -> None:
        """노드 상태, ROS 파라미터, 구독자, 발행자와 타이머를 초기화한다."""

        super().__init__('status_node')                     # 노드명

        self.declare_parameter('robot_id', 'PK_01')         # 로봇 식별자
        self.declare_parameter('map_revision', '')
        self.declare_parameter('sensor_timeout_s', 1.5)     # 센서 타임아웃(초)
        # map 은 두 로봇이 공유하므로 접두사가 없다. base 프레임에는 URDF 의
        # `frame_prefix` 가 로봇 접두사를 붙여 두었으므로 launch 가 그 이름을 준다.
        self.declare_parameter('map_frame', 'map')
        self.declare_parameter('base_frame_id', 'base_footprint')
        self.robot_id = self.get_parameter('robot_id').value
        self.map_revision = self.get_parameter('map_revision').value
        self.timeout = float(self.get_parameter('sensor_timeout_s').value)
        self.map_frame = self.get_parameter('map_frame').value
        self.base_frame_id = self.get_parameter('base_frame_id').value

        # 각 센서 메시지를 마지막으로 받은 ROS 시계 시각; 초기 상태는 0.0 -> stale
        self.last_scan = self.last_odom = self.last_battery = 0.0
        self.odom: Odometry | None = None
        self.battery = 0.0

        # map 좌표 pose 는 토픽이 아니라 TF 에서 읽는다.
        #
        # nav2 AMCL 은 `amcl_pose` 를 이벤트로만 낸다 — 첫 스캔에 한 번, 그 뒤로는
        # 로봇이 `update_min_d` 만큼 움직여 재표집될 때만이다. 그래서 그 토픽의
        # 신선도는 위치추정이 살아 있는지가 아니라 로봇이 움직였는지를 잰다.
        # 충전기에 세워 둔 로봇은 그 때문에 영영 못 움직였다. amcl_pose 가 한 번
        # 오고 timeout 이 지나면 `map_pose_stale` 이 되어 frame_id 가 odom 으로
        # 떨어지고, adapter 는 frame_id 가 `map` 이 아닌 로봇을 거부하고, job 이
        # 배정되지 않으니 로봇은 움직이지 않고, 움직이지 않으니 amcl_pose 도 다시
        # 오지 않는다.
        #
        # AMCL 이 지속적으로 내보내는 것은 `map -> odom` 변환이다. 그것을 조회하면
        # 위치추정이 지금 살아 있는지를 그대로 알 수 있고, 최신 odometry 까지
        # 합성된 pose 를 얻는다. nav2 자신의 소비자도 모두 TF 를 본다.
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        self.task_context = TaskContext()
        self.nav_available = False
        self.control_link_online = False

        # 초기 주행 상태
        self.navigation_state = NavigationState.STATE_IDLE      # 대기
        self.task_progress = 0.0                                # 작업 진행률

        self.safety = SafetyState()
        self.cargo = CargoState()
        self.battery_policy = BatteryPolicyState()

        self.create_subscription(LaserScan, 'scan', self._scan, 10)
        self.create_subscription(Odometry, 'odom', self._odom, 10)
        self.create_subscription(BatteryState, 'trihouse/battery', self._battery, 10)
        self.create_subscription(BatteryCondition, 'trihouse/battery/condition', self._battery_condition, 10)
        self.create_subscription(SafetyState, 'trihouse/safety/state', self._safety, 10)
        self.create_subscription(CargoState, 'trihouse/cargo/state', self._cargo, 10)
        self.create_subscription(BatteryPolicyState, 'trihouse/battery/policy_state', lambda m: setattr(self, 'battery_policy', m), 10)
        self.create_subscription(NavigationState, 'trihouse/navigation/state', self._navigation, 10)
        self.create_subscription(Readiness, 'trihouse/readiness', self._readiness, 10)
        self.create_subscription(
            ConnectionState,
            'trihouse/fms/state',
            self._connection,
            CONNECTION_STATE_QOS,
        )

        self.publisher = self.create_publisher(RobotStatus, 'trihouse/status', 10)

        self.create_timer(1.0, self._publish)   # heartbeat가 유지되도록 1초마다 _publish를 호출한다.

    def _now(self) -> float:
        """신선도를 재는 기준 시각을 초로 낸다.

        `time.monotonic()` 을 쓰면 안 된다. `use_sim_time` 이 켜지면 발행자의
        타이머는 sim 시간으로 뛰는데 이쪽만 벽시계로 재면 두 값이 다른 시계에
        놓인다. 시뮬이 실시간보다 느리면 1 sim초 주기로 오는 배터리가 벽시계로는
        몇 초 간격이 되어 임계값을 늘 넘고, 영구히 stale 로 판정된다. 실기에서는
        ROS 시계가 곧 벽시계이므로 동작이 달라지지 않는다.
        """
        return self.get_clock().now().nanoseconds / 1e9

    def _scan(self, _: LaserScan) -> None:
        """라이다 데이터의 마지막 수신 시각을 기록한다."""

        # 메시지 내용은 사용하지 않으므로 인자 이름을 `_`로 표시한다.
        self.last_scan = self._now()

    def _odom(self, message: Odometry) -> None:
        """최신 위치·속도와 odometry 수신 시각을 기록한다."""
        self.odom = message                                 # pose와 twist를 복사할 원본 메시지를 보관한다.
        self.last_odom = self._now()

    def _lookup_map_pose(self):
        """`map -> base` 변환을 조회한다. 없거나 낡으면 None 을 낸다.

        가장 최근 변환을 받아 그 시각을 지금과 견준다. 시각을 `now()` 로 지정해
        조회하면 아직 오지 않은 미래를 요구해 늘 실패하므로 그렇게 하지 않는다.
        낡은 변환을 그냥 쓰면 AMCL 이 죽은 뒤에도 map pose 가 있는 것처럼 보이므로
        신선도는 반드시 여기서 확인한다.
        """
        try:
            transform = self.tf_buffer.lookup_transform(
                self.map_frame, self.base_frame_id, Time()
            )
        except tf2_ros.TransformException:
            return None

        stamp = Time.from_msg(transform.header.stamp)
        age_s = (self.get_clock().now() - stamp).nanoseconds / 1e9
        if age_s > self.timeout:
            return None
        return transform

    def _battery(self, message: BatteryState) -> None:
        """최신 배터리 잔량과 배터리 메시지 수신 시각을 기록한다."""
        self.battery = message.percentage * 100.0           # BatteryState.percentage의 0.0~1.0 비율을 0.0~100.0 값으로 바꾼다.
        self.last_battery = self._now()

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
        self.task_context = message.task_context

        # 주행 상태 상수와 작업 진행률을 저장한다.
        self.navigation_state = message.state
        self.task_progress = message.progress

        # 주행 상태 변경을 중앙 시스템이 바로 알 수 있도록 즉시 발행한다.
        self._publish()
        if message.state in (
            NavigationState.STATE_SUCCEEDED,
            NavigationState.STATE_CANCELED,
            NavigationState.STATE_FAILED,
        ):
            # terminal 상태가 한 번 관측된 뒤 다음 heartbeat는 유휴 상태여야 한다.
            # 이전 command context를 계속 재전송하면 FMS가 완료 step을 실행 중으로
            # 오인하므로 로컬 snapshot을 즉시 비활성 context로 되돌린다.
            self.task_context = TaskContext()
            self.navigation_state = NavigationState.STATE_IDLE
            self.task_progress = 0.0

    def _readiness(self, message: Readiness) -> None:
        self.nav_available = message.state == Readiness.STATE_READY

    def _connection(self, message: ConnectionState) -> None:
        self.control_link_online = message.state == ConnectionState.STATE_ONLINE

    def _publish(self) -> None:
        """현재까지 수집한 값으로 RobotStatus를 조합해 발행한다."""

        self.publisher.publish(self._build_message())

    def _build_message(self) -> RobotStatus:
        """현재 저장된 입력을 하나의 RobotStatus 메시지로 조합한다."""

        # 모든 경과 시간 계산이 같은 기준 시각을 사용하도록 현재 시각을 한 번 읽는다.
        now = self._now()

        # 한 메시지 안에서 판정과 pose 가 같은 조회 결과를 쓰도록 한 번만 읽는다.
        map_transform = self._lookup_map_pose()

        # 각 센서가 timeout 이내에 들어왔는지를 정책 입력으로 전달한다.
        # build_status는 이 정보로 작업 할당 가능 여부와 오류 목록을 계산한다.
        summary = build_status(
            StatusInputs(
                robot_id=self.robot_id,
                scan_fresh=now - self.last_scan <= self.timeout,
                odom_fresh=now - self.last_odom <= self.timeout,
                battery_fresh=now - self.last_battery <= self.timeout,
                map_pose_fresh=map_transform is not None,
                nav_available=self.nav_available,
                control_link_online=self.control_link_online,
                safety_clear=safety_allows_work(self.safety.state),
                battery_dispatchable=self.battery_policy.ready,
            )
        )

        message = RobotStatus() # RobotStatus 메시지 타입의 인스턴스를 생성한다.

        # ROS clock의 현재 시각을 builtin_interfaces/Time 메시지로 변환한다.
        message.stamp = self.get_clock().now().to_msg()

        # 이 상태를 보낸 로봇과 현재 작업의 식별 정보를 채운다.
        message.robot_id = self.robot_id
        message.map_revision = self.map_revision or self.task_context.map_revision
        message.task_context = self.task_context

        # 순수 상태 정책이 계산한 준비 여부와 오류 tuple을 ROS 배열로 복사한다.
        message.ready = summary.ready
        message.telemetry_valid = summary.telemetry_valid
        message.execution_ready = summary.execution_ready
        message.dispatchable = summary.dispatchable
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

        # RMF에는 odom 좌표를 map 좌표처럼 전달하면 안 된다. 신선한 map 변환이
        # 있으면 이를 우선하고, 없거나 stale이면 frame_id를 odom으로 남겨 상위
        # adapter가 등록/갱신을 거절할 수 있게 한다.
        #
        # covariance 는 채우지 않는다. TF 에는 그 값이 없고, 저장소 안에 이 필드를
        # 읽는 곳도 없다. 필요해지면 그때 근거와 함께 넣는다.
        if map_transform is not None:
            translation = map_transform.transform.translation
            message.pose.pose.position.x = translation.x
            message.pose.pose.position.y = translation.y
            message.pose.pose.position.z = translation.z
            message.pose.pose.orientation = map_transform.transform.rotation
            message.frame_id = self.map_frame
        elif self.odom is not None:
            message.pose.pose = self.odom.pose.pose
            message.frame_id = self.odom.header.frame_id

        if self.odom is not None:
            message.twist = self.odom.twist.twist

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
