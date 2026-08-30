"""SR_23·54의 최종 Pinky 속도 gate를 ROS topic/service로 연결하는 node."""

from time import monotonic
from math import hypot

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)
from sensor_msgs.msg import LaserScan, Range
from nav_msgs.msg import Odometry
from std_msgs.msg import Bool
from trihouse_interfaces.msg import ConnectionState, IndicatorState, KeepOutZone, PersonDetection, SafetyState
from trihouse_interfaces.srv import ClearEmergency

from .geometry import (
    FOOTPRINT_FRONT_M,
    FOOTPRINT_REAR_M,
    PROTECTIVE_HALF_WIDTH_M,
    SCAN_FORWARD_OFFSET_RAD,
    SCAN_ORIGIN_OFFSET_X_M,
    SWEPT_CONTACT_M,
    nearest_range,
    path_clearance,
    point_in_polygon,
    rotating_in_place,
    swept_clearance_blocked,
)
from .policy import (
    MotionCommand,
    SafetyConfig,
    SafetyInputs,
    apply_safety_gate,
    select_manual_command,
    select_motion_source,
)


# `trihouse/fms/state` 는 흘러가는 사건이 아니라 **최신 값이 계속 유효한 사실**이다.
# `gateway_node` 는 연결 상태가 바뀔 때만 발행하므로, 늦게 뜬 구독자가 그 한 번을
# 놓치면 영원히 모른다. 이 gate 는 모터 `/cmd_vel` 의 유일한 발행자라, 놓치면
# `control_link_lost` STOP 이 걸린 채 로봇이 RMF 에서 빠진다.
#
# `gateway_node`·`status_node` 의 같은 이름 상수와 값이 같아야 한다 —
# `test_connection_state_qos_contract.py` 가 셋을 묶는다. 여기서 따로 두는 이유는
# `trihouse_pinky_safety` 가 `trihouse_pinky_fleet` 에 의존하지 않기 때문이다.
CONNECTION_STATE_QOS = QoSProfile(
    depth=1,
    history=QoSHistoryPolicy.KEEP_LAST,
    reliability=QoSReliabilityPolicy.RELIABLE,
    durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
)

# EN: LaserScan is a current observation, not an event ledger. Under load,
# RELIABLE delivery replays obsolete geometry and can keep the robot stopped.
# KO: LaserScan은 사건 원장이 아니라 현재 관측이다. 부하 시 RELIABLE 재전송은
# 과거 장애물을 재생해 로봇을 계속 정지시킬 수 있다.
SAFETY_SCAN_QOS = QoSProfile(
    depth=1,
    history=QoSHistoryPolicy.KEEP_LAST,
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    durability=QoSDurabilityPolicy.VOLATILE,
)


class SafetySupervisor(Node):
    """The only operational publisher for the motor `/cmd_vel` topic."""
    def __init__(self) -> None:
        super().__init__('safety_supervisor')
        self.declare_parameter('robot_id', 'PK_01')
        # 라이다 10 Hz 기준 1.0 s 는 **10 스캔 연속 실종**이다. 그래도 fail-safe 다.
        # 이전 값 0.5 s 는 실기 부하를 못 견뎌 gate 를 깜빡이게 했고, 그 깜빡임이
        # 로봇을 RMF 에서 빼냈다 — 2026-08-24 실측에서 `sensor_timeout` 이 423 샘플,
        # 그중 414 초가 한 구간이었다.
        self.declare_parameter('sensor_timeout_s', 1.0)
        self.declare_parameter('stop_distance_m', 0.05)
        # `policy.SafetyConfig.slow_distance_m` 과 같은 이유로 지금은 판정에
        # 쓰이지 않는다. 값만 넘어가고 게이트는 사람 검출로만 감속한다.
        self.declare_parameter('slow_distance_m', 0.25)
        self.declare_parameter('slow_linear_speed_mps', 0.08)
        # 초음파를 필수 센서로 보지 않는다.
        #
        # `sensor_fresh` 는 `scan_fresh and (range_fresh or not require_ultrasonic)`
        # 이라, True 면 **초음파 하나가 끊길 때 라이다가 멀쩡해도 전 주행이 정지**한다.
        # 두 번째 거부권을 주는 셈인데, 정작 초음파는 정면만 보고 센서 원점 기준
        # raw range 를 낸다 — `path_clearance` 의 몸끝 기준 여유와 의미가 다른 값을
        # 같은 `stop_distance_m` 에 걸어 `min()` 으로 경쟁시켜 왔다.
        self.declare_parameter('require_ultrasonic', False)
        # waypoint 측정 전용 local-manual에서는 관제 연결 없이도 허용하되,
        # 라이다·초음파·비상정지·보호 필드는 동일하게 적용한다.
        self.declare_parameter('manual_mode_enabled', False)
        self.declare_parameter('manual_command_timeout_s', 0.25)
        self.declare_parameter('person_protective_distance_m', 1.0)
        # marker dock이 종료하며 남긴 zero Twist가 Nav2 주행을 영구히 막지 않게
        # 한다. docking node의 20 Hz 제어 주기보다 넉넉하고, stale 명령은 짧게
        # 잊는 값이다.
        self.declare_parameter('dock_command_timeout_s', 0.25)
        # 안전 필드의 모양. 기본값의 근거는 `geometry.py` 에 적었고
        # `test_safety_fields_match_the_robot.py` 가 벤더 URDF·Nav2 발자국과 묶는다.
        self.declare_parameter('scan_forward_offset_rad', SCAN_FORWARD_OFFSET_RAD)
        self.declare_parameter('scan_origin_offset_x_m', SCAN_ORIGIN_OFFSET_X_M)
        self.declare_parameter('protective_half_width_m', PROTECTIVE_HALF_WIDTH_M)
        self.declare_parameter('footprint_front_m', FOOTPRINT_FRONT_M)
        self.declare_parameter('footprint_rear_m', FOOTPRINT_REAR_M)
        # 회전 중 접촉 감지 문턱. **발자국 외접반경(`SWEPT_RADIUS_M`)이 아니다** —
        # 회전 충돌 방지는 Nav2 가 맡는다. 값의 근거와 포기한 것은
        # `geometry.SWEPT_CONTACT_M` 의 주석에 적었다.
        self.declare_parameter('swept_clearance_m', SWEPT_CONTACT_M)
        self.scan_forward_offset_rad = float(self.get_parameter('scan_forward_offset_rad').value)
        self.scan_origin_offset_x_m = float(self.get_parameter('scan_origin_offset_x_m').value)
        self.protective_half_width_m = float(self.get_parameter('protective_half_width_m').value)
        self.footprint_front_m = float(self.get_parameter('footprint_front_m').value)
        self.footprint_rear_m = float(self.get_parameter('footprint_rear_m').value)
        self.swept_clearance_m = float(self.get_parameter('swept_clearance_m').value)
        self.robot_id = self.get_parameter('robot_id').value
        self.sensor_timeout_s = float(self.get_parameter('sensor_timeout_s').value)
        self.config = SafetyConfig(float(self.get_parameter('stop_distance_m').value), float(self.get_parameter('slow_distance_m').value), float(self.get_parameter('slow_linear_speed_mps').value), float(self.get_parameter('person_protective_distance_m').value))
        self.require_ultrasonic = bool(self.get_parameter('require_ultrasonic').value)
        self.manual_mode_enabled = bool(self.get_parameter('manual_mode_enabled').value)
        self.manual_command_timeout_s = float(
            self.get_parameter('manual_command_timeout_s').value
        )
        self.dock_command_timeout_s = float(
            self.get_parameter('dock_command_timeout_s').value
        )
        self.nav = MotionCommand(0.0, 0.0)
        self.manual = MotionCommand(0.0, 0.0)
        self.last_manual_at = float('-inf')
        self.dock: MotionCommand | None = None
        self.last_dock_at = float('-inf')
        self.front_range: float | None = None
        self.forward_clearance: float | None = None
        self.reverse_clearance: float | None = None
        self.nearby_range: float | None = None
        self.person_detected = False
        self.person_distance = None
        self.person_pose_class = ""
        self.person_until = 0.0
        self.keep_out_zones: dict[str, KeepOutZone] = {}
        self.position: tuple[float, float] | None = None
        self.emergency_latched = False
        self.control_link_online = False
        self.last_sensor_at = 0.0
        self.last_range_at = 0.0
        self.last_scan_at = 0.0
        self.create_subscription(Twist, 'cmd_vel_nav', self._on_nav, 10)
        self.create_subscription(Twist, 'cmd_vel_manual', self._on_manual, 10)
        self.create_subscription(Twist, 'cmd_vel_dock', self._on_dock, 10)
        self.create_subscription(Range, 'trihouse/proximity/front', self._on_range, 10)
        # EN: Safety must act on the newest scan. A reliable depth-10 queue can
        # replay old wall returns after CPU contention and apply them at a new pose.
        # KO: 안전 판정은 최신 scan만 사용해야 한다. depth 10 큐는 CPU 경합 뒤
        # 예전 벽 반사를 새 pose에 적용할 수 있으므로 backlog를 만들지 않는다.
        self.create_subscription(LaserScan, 'scan', self._on_scan, SAFETY_SCAN_QOS)
        self.create_subscription(PersonDetection, 'trihouse/vision/person_detection/base', self._on_person, 10)
        self.create_subscription(KeepOutZone, 'trihouse/safety/keep_out_zones', self._on_keep_out, 10)
        self.create_subscription(Odometry, 'odom', self._on_odom, 10)
        self.create_subscription(ConnectionState, 'trihouse/fms/state', self._on_connection, CONNECTION_STATE_QOS)
        # Vision detects; the Control Tower/Safety authority explicitly requests emergency.
        self.create_subscription(Bool, 'trihouse/safety/emergency_request', self._on_emergency_request, 10)
        self.cmd_pub = self.create_publisher(Twist, 'cmd_vel', 10)
        self.state_pub = self.create_publisher(SafetyState, 'trihouse/safety/state', 10)
        self.indicator_pub = self.create_publisher(IndicatorState, 'trihouse/indicator/state', 10)
        self.create_service(ClearEmergency, 'trihouse/safety/clear_emergency', self._clear_emergency)
        self.create_timer(0.05, self._publish)

    def _on_nav(self, message: Twist) -> None:
        self.nav = MotionCommand(message.linear.x, message.angular.z)

    def _on_manual(self, message: Twist) -> None:
        self.manual = MotionCommand(message.linear.x, message.angular.z)
        self.last_manual_at = monotonic()

    def _on_dock(self, message: Twist) -> None:
        self.dock = MotionCommand(message.linear.x, message.angular.z)
        self.last_dock_at = monotonic()

    def _on_range(self, message: Range) -> None:
        self.front_range = message.range; self.last_range_at = monotonic(); self.last_sensor_at = self.last_range_at

    def _on_scan(self, message: LaserScan) -> None:
        stamp_ns = (
            int(message.header.stamp.sec) * 1_000_000_000
            + int(message.header.stamp.nanosec)
        )
        age_ns = self.get_clock().now().nanoseconds - stamp_ns
        timeout_ns = int(self.sensor_timeout_s * 1_000_000_000)
        # EN: DDS may deliver a reliable backlog after the robot has moved. The
        # receive time cannot make that old geometry current at the new pose.
        # KO: 로봇 이동 뒤 reliable DDS backlog가 도착할 수 있다. 수신 시각으로
        # 과거 장애물을 새 pose의 현재 장애물처럼 되살려서는 안 된다.
        if stamp_ns <= 0 or age_ns < -timeout_ns or age_ns > timeout_ns:
            return
        # 한 스캔에서 필드 두 개를 뽑는다. 360 도 최솟값 하나를 STOP 판정에 쓰면
        # 2.20 x 2.70 m 방에서는 늘 stop_distance_m 안이라 로봇이 영구히 STOP 에
        # 걸린다 (2026-08-20 실측). 그리고 늘 울리는 경보는 정보가 0 이다.
        shape = dict(
            angle_min=message.angle_min,
            angle_increment=message.angle_increment,
            range_min=message.range_min,
            range_max=message.range_max,
            forward_offset_rad=self.scan_forward_offset_rad,
            origin_offset_x_m=self.scan_origin_offset_x_m,
        )
        # 진행 방향은 스캔이 올 때가 아니라 명령을 낼 때 정해진다. 여기서는
        # 두 방향을 다 재 두고 `_publish` 가 그때의 명령으로 고른다.
        self.forward_clearance = path_clearance(
            message.ranges, half_width_m=self.protective_half_width_m,
            reverse=False, front_extent_m=self.footprint_front_m,
            rear_extent_m=self.footprint_rear_m, **shape
        )
        self.reverse_clearance = path_clearance(
            message.ranges, half_width_m=self.protective_half_width_m,
            reverse=True, front_extent_m=self.footprint_front_m,
            rear_extent_m=self.footprint_rear_m, **shape
        )
        self.nearby_range = nearest_range(message.ranges, **shape)
        self.last_scan_at = monotonic(); self.last_sensor_at = self.last_scan_at

    def _on_person(self, message: PersonDetection) -> None:
        self.person_detected = message.confidence > 0.0
        position = message.pose.pose.position
        self.person_distance = hypot(position.x, position.y)
        # 자세 상태를 그대로 들고 있는다. 쓰러진 사람은 서 있는 사람과 다른
        # 위험이고, 그 구분은 여기 말고는 만들 데가 없다.
        self.person_pose_class = message.pose_class or ""
        self.person_until = monotonic() + max(message.ttl_ms, 1) / 1000.0

    def _on_keep_out(self, message: KeepOutZone) -> None:
        self.keep_out_zones[message.zone_id] = message

    def _on_odom(self, message: Odometry) -> None:
        pose = message.pose.pose.position
        self.position = (pose.x, pose.y)

    def _on_connection(self, message: ConnectionState) -> None:
        """관제 재연결이 곧 자동 재개가 되지 않도록 online 상태만 safety 입력으로 반영한다."""
        self.control_link_online = message.state == ConnectionState.STATE_ONLINE

    def _on_emergency_request(self, message: Bool) -> None:
        if message.data:
            self.emergency_latched = True

    def _clear_emergency(self, request: ClearEmergency.Request, response: ClearEmergency.Response) -> ClearEmergency.Response:
        if request.robot_id != self.robot_id or not request.operator_id:
            response.accepted, response.message = False, 'robot_id or operator_id is invalid'
            return response
        self.emergency_latched = False
        response.accepted, response.message = True, 'emergency latch cleared; fleet must start return inspection'
        response.cleared_at = self.get_clock().now().to_msg()
        return response

    def _publish(self) -> None:
        now = monotonic()
        if self.manual_mode_enabled:
            desired = select_manual_command(
                self.manual,
                now_s=now,
                received_at_s=self.last_manual_at,
                timeout_s=self.manual_command_timeout_s,
            )
        else:
            desired = select_motion_source(
                self.nav,
                self.dock,
                now_s=now,
                dock_received_at_s=self.last_dock_at,
                dock_timeout_s=self.dock_command_timeout_s,
            )
        person_detected = self.person_detected and monotonic() <= self.person_until
        scan_fresh = now - self.last_scan_at <= self.sensor_timeout_s
        range_fresh = now - self.last_range_at <= self.sensor_timeout_s
        # 보호 필드의 모양은 **지금 내리려는 명령**을 따른다. 제자리 회전은
        # 외접원을 쓸고 지나가므로 경로(직사각형) 판정으로는 잡히지 않는다.
        nearby = self.nearby_range if scan_fresh else None
        swept_blocked = (
            rotating_in_place(desired.linear_x, desired.angular_z)
            and nearby is not None
            and swept_clearance_blocked(nearby, self.swept_clearance_m)
        )
        path_distance = self._path_distance(desired.linear_x, desired.angular_z)
        inputs = SafetyInputs(sensor_fresh=scan_fresh and (range_fresh or not self.require_ultrasonic),
                              front_distance_m=path_distance,
                              swept_blocked=swept_blocked,
                              person_detected=person_detected,
                              person_distance_m=self.person_distance if person_detected else None,
                              # TTL 이 지난 관측의 자세를 계속 들고 있으면, 사람이
                              # 사라진 뒤에도 "쓰러짐" 이 붙은 채 판단에 들어간다.
                              person_pose_class=self.person_pose_class if person_detected else "",
                              keep_out=self._in_keep_out_zone(), emergency_latched=self.emergency_latched,
                              control_link_fresh=(self.manual_mode_enabled or self.control_link_online))
        decision = apply_safety_gate(desired, inputs, self.config)
        if decision.reason == "front_stop":
            # EN: A rejected motion must expose the measured clearance in the
            # runtime log; otherwise a sensor-model fault looks like Nav2 failure.
            # KO: 주행 거부 시 측정 여유를 런타임 로그에 남겨야 센서 모델 결함을
            # Nav2 실패로 오인하지 않는다.
            self.get_logger().warning(
                f"front_stop: desired=({desired.linear_x:.3f}, "
                f"{desired.angular_z:.3f}) "
                f"path_clearance={path_distance} "
                f"scan_nearby={nearby} scan_age={now - self.last_scan_at:.3f}",
                throttle_duration_sec=2.0,
            )
        elif decision.reason == "swept_stop":
            self.get_logger().warning(
                f"swept_stop: desired=({desired.linear_x:.3f}, "
                f"{desired.angular_z:.3f}) scan_nearby={nearby} "
                f"threshold={self.swept_clearance_m:.3f} "
                f"scan_age={now - self.last_scan_at:.3f}",
                throttle_duration_sec=2.0,
            )
        cmd = Twist(); cmd.linear.x = decision.command.linear_x; cmd.angular.z = decision.command.angular_z
        self.cmd_pub.publish(cmd)
        state = SafetyState(); state.stamp = self.get_clock().now().to_msg(); state.robot_id = self.robot_id
        state.state = int(decision.level); state.latched = self.emergency_latched; state.source = 'safety_supervisor'; state.detail = decision.reason
        self.state_pub.publish(state)
        indicator = IndicatorState(); indicator.stamp = state.stamp; indicator.robot_id = self.robot_id
        indicator.state = IndicatorState.STATE_EMERGENCY if self.emergency_latched else (IndicatorState.STATE_PERSON_DETECTED if person_detected and self.person_distance is not None and self.person_distance <= self.config.person_protective_distance_m else IndicatorState.STATE_OFF)
        indicator.source = 'safety_supervisor'; indicator.detail = decision.reason
        self.indicator_pub.publish(indicator)

    def _path_distance(
        self, commanded_linear_x: float, commanded_angular_z: float
    ) -> float | None:
        """진행 방향의 여유. 후진이면 뒤쪽 필드를 본다.

        초음파는 정면(`ultrasonic_link`)만 보므로 후진에는 근거가 되지 못한다.
        후진 여유는 라이다만으로 재고, 그 사실을 여기서 명시적으로 가른다 —
        섞으면 뒤가 막혔는데 초음파의 "정면 3 m" 가 이겨 통과해 버린다.
        """
        # EN: Rotation has no forward/reverse path. Its complete collision
        # envelope is already checked by the swept-radius field.
        # KO: 제자리 회전에는 전진/후진 경로가 없고, 전체 충돌 영역은 위의
        # 회전 외접반경 필드에서 이미 검사한다.
        if rotating_in_place(commanded_linear_x, commanded_angular_z):
            return None
        now = monotonic()
        reversing = commanded_linear_x < 0.0
        scan = self.reverse_clearance if reversing else self.forward_clearance
        candidates = []
        if scan is not None and now - self.last_scan_at <= self.sensor_timeout_s:
            candidates.append(scan)
        if not reversing and self.front_range is not None and now - self.last_range_at <= self.sensor_timeout_s:
            candidates.append(self.front_range)
        return min(candidates) if candidates else None

    def _in_keep_out_zone(self) -> bool:
        if self.position is None:
            return False
        now = self.get_clock().now().nanoseconds
        for zone in self.keep_out_zones.values():
            valid_until = zone.valid_until.sec * 1_000_000_000 + zone.valid_until.nanosec
            if valid_until and valid_until < now:
                continue
            points = tuple((point.x, point.y) for point in zone.polygon.points)
            if len(points) >= 3 and point_in_polygon(*self.position, points):
                return True
        return False


def main() -> None:
    rclpy.init(); node = SafetySupervisor()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node(); rclpy.shutdown()
