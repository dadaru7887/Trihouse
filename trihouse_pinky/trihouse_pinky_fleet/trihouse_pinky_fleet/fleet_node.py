"""Pinky 운반 요청을 Nav2 action과 창고 협로 규칙 주행으로 바꾸는 adapter."""

import copy
import rclpy
from math import atan2, cos, hypot, isfinite, sin

import yaml
from pathlib import Path
from uuid import uuid4
from builtin_interfaces.msg import Duration
from nav2_msgs.action import BackUp, DriveOnHeading, NavigateToPose, Spin, Wait
from geometry_msgs.msg import PoseStamped, Twist
from nav_msgs.msg import OccupancyGrid, Odometry
from sensor_msgs.msg import LaserScan
from rclpy.action import ActionClient, ActionServer
from rclpy.action import CancelResponse
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.task import Future
from std_msgs.msg import Bool, String
from trihouse_interfaces.action import Dock, ExecuteRecovery, ExecuteTransport
from trihouse_interfaces.msg import HandoverState, NavigationState, Readiness, RobotHealth, RobotStatus, SafetyState, TaskEvent
from trihouse_pinky_docking.narrow_zone import (
    ENTER,
    EXIT,
    MotionLimits,
    NarrowZoneConfigError,
    NarrowZoneController,
    Pose2D,
    load_narrow_zones,
)

from .workflow import JobCommand, JobPhase, TransportWorkflow
from .narrow_zone_pilot import verify_pose
from .narrow_zone_routing import departure_profile, select_approach
from .arrival import may_report_arrival, within_tolerance
from .recovery_execution import recovery_admission_block_reason


def _complete_once(future: Future) -> None:
    """timer 가 두 번 발화해도 Future 를 한 번만 완료시킨다."""
    if not future.done():
        future.set_result(None)


def _duration(seconds: float) -> Duration:
    whole = int(seconds)
    return Duration(sec=whole, nanosec=int((seconds - whole) * 1_000_000_000))


# 정밀 정차 허용오차. **Nav2 의 goal tolerance 보다 좁으면 안 된다.**
#
# Nav2 는 `xy_goal_tolerance` 안에 들어오면 그 자리에서 멈추고 SUCCEEDED 를 준다.
# 그보다 좁은 기준으로 도착을 다시 판정하면 Nav2 가 정상 종료한 이동을 우리가
# 거절하게 되고, 로봇은 더 갈 이유가 없으므로 재시도해도 같은 자리에 선다 —
# 재시도로 풀리지 않는 실패다. 2026-08-19 실측에서 step 20 이
# `GOAL_TOLERANCE_NOT_MET` 으로 죽은 것이 이것이다(우리 0.05 대 Nav2 0.1).
#
# 값의 정본은 `pinky_pro/pinky_navigation/params/nav2_params.yaml` 이다 — 실물
# 주행으로 튜닝한 값이라 우리 편의로 조이지 않는다. AMCL 실측 stddev 가 10~12 cm
# 이므로 그보다 좁은 허용오차는 위치추정 정확도로도 만족시킬 수 없다.
#
# **같게 두어도 안 된다.** Nav2 는 허용오차 *안에 들어오는 순간* 멈추므로 로봇은
# 늘 그 경계선 위에 선다. 같은 값으로 다시 재면 AMCL 노이즈(실측 stddev 10~12 cm)
# 에 따라 통과와 실패가 갈리는 동전 던지기가 된다. 2026-08-19 실측: 병목 구간이
# 끝난 자리에서 목표까지 거리가 정확히 0.100 m 였고 step 20 이
# `GOAL_TOLERANCE_NOT_MET` 으로 죽었다. Nav2 가 이미 0.1 을 보장하므로 여기서는
# 그것을 다시 재는 것이 아니라 **크게 어긋나지 않았는지만** 본다.
#
# 두 값의 관계는 `test_precise_stop_matches_nav2_tolerance.py` 가 지킨다.
# 규칙 주행 속도. 통로 폭 0.20 m 에 로봇 폭 0.12 m 라 여유가 편측 4 cm 다.
# 빠르면 오도메트리 오차가 그 여유를 넘는다. 원본 narrow3 이 쓰던 값이다.
NARROW_MAX_LINEAR_MPS = 0.06
NARROW_MAX_ANGULAR_RPS = 0.5
NARROW_YAW_TOLERANCE_RAD = 0.05
NARROW_POSITION_TOLERANCE_M = 0.02
# 스텝 하나의 상한. 넘으면 바퀴가 헛돌거나 끼인 것이다. 되먹임이 없으므로 시간으로만
# 알 수 있다.
NARROW_STEP_TIMEOUT_S = 25.0

PRECISE_STOP_XY_TOLERANCE_M = 0.15
PRECISE_STOP_YAW_TOLERANCE_RAD = 0.35


def _warn(node: object, message: str) -> None:
    """관측용 경고.

    메서드가 아니라 모듈 함수인 이유: 정밀 정차 계약 테스트는 클래스에서
    `_at_precise_goal` 하나만 빌려다 쓰는 최소 stub 을 만든다. 메서드를 늘리면
    그 stub 이 깨진다. 로거가 없는 환경에서는 조용히 넘어간다.
    """
    logger = getattr(node, "get_logger", None)
    if logger is not None:
        logger().warn(message)


def transport_admission_block_reason(outbox_ready: bool) -> str | None:
    return None if outbox_ready else 'task event outbox capacity reached'


def transport_arrival_succeeded(outcome: object) -> bool:
    """Accept only an affirmative workflow outcome in a terminal good phase."""
    return bool(
        outcome.accepted
        and outcome.phase in (JobPhase.WAITING_HANDOVER, JobPhase.IDLE)
    )


class FleetNode(Node):
    """Translates an FMS-approved action to exactly one Nav2 goal."""
    def __init__(self) -> None:
        super().__init__('fleet_node')
        self.declare_parameter('robot_id', 'PK_01'); self.declare_parameter('map_revision', '')
        # Nav2 SUCCEEDED 와 실제 정차 사이의 감쇠 시간을 기다리는 상한.
        # 끝내 멈추지 않는 것은 실제 결함이므로 무한히 기다리지 않는다 —
        # 그때는 goal 이 ROBOT_NOT_STOPPED 로 정직하게 실패하는 편이
        # action 이 영원히 매달려 있는 것보다 낫다.
        self.declare_parameter('arrival_stop_timeout_s', 2.0)
        self.robot_id = self.get_parameter('robot_id').value
        self.map_revision = self.get_parameter('map_revision').value
        self.workflow = TransportWorkflow(robot_id=self.robot_id, expected_map_revision=self.map_revision)
        self.ready = False; self.outbox_ready = False; self.emergency = False; self.stationary = False; self.recovery_health_ok = False; self.current_pose: tuple[float, float, float] | None = None
        self.safety_seen = False
        self.nearest_lidar_range_m: float | None = None
        # 정밀 정차 판정용 map 프레임 pose. odom 은 프레임이 달라 쓸 수 없다.
        self.map_pose: tuple[float, float, float] | None = None
        self.map_frame: str = ""
        self.navigation_pub = self.create_publisher(NavigationState, 'trihouse/navigation/state', 10)
        self.event_pub = self.create_publisher(TaskEvent, 'trihouse/task/events', 10)
        self.handover_pub = self.create_publisher(HandoverState, '/trihouse/handover/state', 10)
        self.display_pub = self.create_publisher(String, 'trihouse/display/destination_code', 10)
        # 규칙 주행은 Nav2와 발행자를 공유하지 않는다. docking 채널로 보내도 실제
        # 모터 `cmd_vel`은 safety supervisor 하나만 발행한다.
        self.narrow_cmd_pub = self.create_publisher(Twist, 'cmd_vel_dock', 10)
        self.create_subscription(Readiness, 'trihouse/readiness', self._on_readiness, 10)
        self.create_subscription(SafetyState, 'trihouse/safety/state', self._on_safety, 10)
        self.create_subscription(RobotHealth, 'trihouse/health', self._on_health, 10)
        self.create_subscription(
            Bool, 'trihouse/fms/event_outbox_ready', self._on_outbox_ready, 10
        )
        self.create_subscription(RobotStatus, 'trihouse/status', self._on_status, 10)
        self.create_subscription(Odometry, 'odom', self._on_odom, 10)
        self.create_subscription(LaserScan, 'scan', self._on_scan, 10)
        # 지도 범위를 알아야 "로봇이 지도 밖"을 판별할 수 있다. map 은 한 번만
        # latch 로 나가므로 transient_local 로 받아야 늦게 뜬 노드도 받는다.
        self.map_bounds: tuple[float, float, float, float] | None = None
        self.create_subscription(
            OccupancyGrid, 'map', self._on_map,
            QoSProfile(
                depth=1,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
                history=HistoryPolicy.KEEP_LAST,
            ),
        )
        # 협로 존 표. 값이 지도 좌표계에 묶여 있어 지도 이름이 맞지 않으면 거절한다.
        self.declare_parameter('narrow_zones_file', '')
        self.declare_parameter('narrow_map_name', '')
        # 기본 false. hardware calibration client의 command_source까지 동시에 맞아야
        # 미실측 후보값으로 한 번의 bounded attempt를 허용한다.
        self.declare_parameter('allow_narrow_calibration', False)
        self.narrow_zones = self._load_narrow_zones()
        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.backup_client = ActionClient(self, BackUp, 'backup')
        self.spin_client = ActionClient(self, Spin, 'spin')
        self.drive_client = ActionClient(self, DriveOnHeading, 'drive_on_heading')
        self.wait_client = ActionClient(self, Wait, 'wait')
        self.dock_client = ActionClient(self, Dock, 'trihouse/dock')
        self.nav_goal_handles = {}
        self.recovery_active = False
        self.recovery_nav_goal_handle = None
        self.recovery_cancel_requested = False
        self.server = ActionServer(
            self,
            ExecuteTransport,
            'trihouse/transport/execute',
            self._execute,
            cancel_callback=self._cancel,
        )
        self.recovery_server = ActionServer(
            self,
            ExecuteRecovery,
            'trihouse/recovery/execute',
            self._execute_recovery,
            cancel_callback=self._cancel_recovery,
        )

    def _on_readiness(self, message: Readiness) -> None:
        self.ready = message.state == Readiness.STATE_READY

    def _on_scan(self, message: LaserScan) -> None:
        valid = [
            float(value) for value in message.ranges
            if isfinite(value) and message.range_min <= value <= message.range_max
        ]
        self.nearest_lidar_range_m = min(valid) if valid else None

    def _on_safety(self, message: SafetyState) -> None:
        self.safety_seen = True
        self.emergency = message.state == SafetyState.STATE_EMERGENCY
        if self.emergency:
            self.workflow.enter_emergency(message.detail)

    def _on_health(self, message: RobotHealth) -> None:
        self.recovery_health_ok = message.state == RobotHealth.STATE_OK

    def _on_outbox_ready(self, message: Bool) -> None:
        self.outbox_ready = bool(message.data)

    def _on_status(self, message: RobotStatus) -> None:
        """map 프레임 pose 를 받아 둔다. 정밀 정차 판정이 이것만 쓴다.

        `_on_odom` 의 pose 는 odom 프레임이라 map 목표와 비교할 수 없다. 로봇이
        spawn 한 자리만큼 언제나 어긋나고 주행하며 드리프트한다. `status_node` 가
        내는 이 메시지는 `frame_id` 를 함께 담으므로 map 인지 확인할 수 있다.
        """
        self.map_frame = str(message.frame_id)
        position = message.pose.pose.position
        orientation = message.pose.pose.orientation
        yaw = atan2(
            2 * (orientation.w * orientation.z + orientation.x * orientation.y),
            1 - 2 * (orientation.y * orientation.y + orientation.z * orientation.z),
        )
        self.map_pose = (position.x, position.y, yaw)

    def _on_odom(self, message: Odometry) -> None:
        twist = message.twist.twist
        self.stationary = abs(twist.linear.x) <= 0.01 and abs(twist.angular.z) <= 0.02
        orientation = message.pose.pose.orientation
        yaw = atan2(2 * (orientation.w * orientation.z + orientation.x * orientation.y), 1 - 2 * (orientation.y * orientation.y + orientation.z * orientation.z))
        position = message.pose.pose.position
        self.current_pose = (position.x, position.y, yaw)

    async def _execute(self, goal_handle: object) -> ExecuteTransport.Result:
        goal = goal_handle.request
        context = goal.task_context
        result = ExecuteTransport.Result()
        if self.recovery_active:
            goal_handle.abort()
            result.success = False
            result.code = ExecuteTransport.Result.CODE_REJECTED
            result.message = 'recovery motion is active'
            return result
        outbox_block = transport_admission_block_reason(self.outbox_ready)
        if outbox_block is not None:
            goal_handle.abort()
            result.success = False
            result.code = ExecuteTransport.Result.CODE_REJECTED
            result.message = outbox_block
            return result
        return_mode = goal.mode in (ExecuteTransport.Goal.MODE_RETURN_TO_WAIT, ExecuteTransport.Goal.MODE_RETURN_TO_CHARGE)
        rmf_navigation = goal.mode == ExecuteTransport.Goal.MODE_RMF_NAVIGATION
        destination_kind = (
            'RETURN_TO_CHARGE'
            if goal.mode == ExecuteTransport.Goal.MODE_RETURN_TO_CHARGE
            else 'RETURN_TO_WAIT'
            if return_mode
            else 'RMF_NAVIGATION'
            if rmf_navigation
            else 'TRANSPORT'
        )
        goal_orientation = goal.dropoff_pose.pose.orientation
        requested_target = Pose2D(
            float(goal.dropoff_pose.pose.position.x),
            float(goal.dropoff_pose.pose.position.y),
            atan2(
                2 * (
                    goal_orientation.w * goal_orientation.z
                    + goal_orientation.x * goal_orientation.y
                ),
                1
                - 2
                * (
                    goal_orientation.y * goal_orientation.y
                    + goal_orientation.z * goal_orientation.z
                ),
            ),
        )
        calibration = bool(
            self.get_parameter('allow_narrow_calibration').value
            and context.command_source == 'hardware_calibration'
        )
        approach = select_approach(
            self.narrow_zones,
            goal.destination_code,
            requested_target,
            calibration=calibration,
        )
        if not approach.allowed:
            goal_handle.abort()
            result.success = False
            result.code = ExecuteTransport.Result.CODE_REJECTED
            result.message = (
                f'{approach.reason_code}: {goal.destination_code} — {approach.reason}'
            )
            result.completed_at = self.get_clock().now().to_msg()
            return result

        # 존 안에서 다음 이동 명령을 받으면 **먼저 규칙 주행으로 빠져나온다.**
        # 이 경로가 없어서 2026-08-19 에 로봇이 냉동창고에서 나오지 못했다 — Nav2 가
        # 통로 안에서 경로를 못 만들어 복구 동작만 반복했다.
        if self.map_pose is not None:
            stuck_in = departure_profile(
                self.narrow_zones, Pose2D(*self.map_pose)
            )
            if stuck_in is not None:
                exit_readiness = stuck_in.direction_readiness_code(EXIT)
                if exit_readiness != 'READY' and not (
                    calibration and stuck_in.calibration_ready(EXIT)
                ):
                    goal_handle.abort()
                    result.success = False
                    result.code = ExecuteTransport.Result.CODE_REJECTED
                    result.message = (
                        f'{exit_readiness}: {stuck_in.destination_code} '
                        f'탈출 profile — {stuck_in.readiness_reason}'
                    )
                    result.completed_at = self.get_clock().now().to_msg()
                    return result
                left, detail = await self._run_narrow_controller(
                    NarrowZoneController(
                        stuck_in,
                        direction=EXIT,
                        limits=self._narrow_limits(),
                        calibration=calibration,
                    ),
                    goal_handle,
                )
                if not left:
                    goal_handle.abort()
                    result.success = False
                    result.code = ExecuteTransport.Result.CODE_NAVIGATION_FAILED
                    result.message = f'협로 탈출 실패: {detail}'
                    result.completed_at = self.get_clock().now().to_msg()
                    return result
                if stuck_in.exit_target is not None:
                    if self.map_pose is None:
                        goal_handle.abort()
                        result.success = False
                        result.code = ExecuteTransport.Result.CODE_NAVIGATION_FAILED
                        result.message = '협로 탈출 뒤 map pose 를 잃었다'
                        result.completed_at = self.get_clock().now().to_msg()
                        return result
                    escaped, distance, yaw_error = verify_pose(
                        self.map_pose,
                        (
                            stuck_in.exit_target.x,
                            stuck_in.exit_target.y,
                            stuck_in.exit_target.yaw,
                        ),
                        xy_tolerance_m=PRECISE_STOP_XY_TOLERANCE_M,
                        yaw_tolerance_rad=PRECISE_STOP_YAW_TOLERANCE_RAD,
                    )
                    self.get_logger().info(
                        f'{stuck_in.destination_code}: 협로 탈출 target 과 거리 '
                        f'{distance:.3f} m, yaw 차 {yaw_error:.3f} rad'
                    )
                    if not escaped:
                        goal_handle.abort()
                        result.success = False
                        result.code = ExecuteTransport.Result.CODE_NAVIGATION_FAILED
                        result.message = (
                            '협로 탈출 target 불일치 '
                            f'(거리 {distance:.3f} m, yaw {yaw_error:.3f} rad)'
                        )
                        result.completed_at = self.get_clock().now().to_msg()
                        return result

        if self.workflow.phase is JobPhase.WAITING_HANDOVER and not return_mode:
            accepted = self.workflow.reassign(
                context.command_id,
                context.map_revision,
                handover_expected=bool(goal.handover_expected),
            )
        else:
            accepted = self.workflow.accept(
                JobCommand(
                    context.command_id,
                    context.job_id,
                    context.map_revision,
                    destination_kind,
                    requires_cargo=not (return_mode or rmf_navigation),
                    handover_expected=bool(goal.handover_expected),
                ),
                ready=self.ready and not self.emergency,
                # EN: Gateway dispatch is the authorization; Pinky has no cargo sensor.
                # KO: Gateway가 적재 증거를 확인한 뒤 명령을 보내며 Pinky에는 화물 센서가 없다.
                cargo_confirmed=True,
            )
        if not accepted.accepted:
            goal_handle.abort(); result.success = False; result.code = ExecuteTransport.Result.CODE_REJECTED; result.message = accepted.detail
            rejection_reasons = {
                'map revision mismatch': 'MAP_REVISION_MISMATCH',
                'robot is not ready': 'SENSOR_TELEMETRY_STALE',
                'cargo handover is not confirmed': 'RESULT_DATA_INCOMPLETE',
                'robot is not idle': 'TASK_CONTEXT_MISMATCH',
            }
            self._publish_navigation(
                goal,
                accepted,
                state_override=NavigationState.STATE_FAILED,
                detail_override=accepted.detail,
            )
            self._publish_event(
                goal, TaskEvent.EVENT_FAILED, accepted.detail,
                reason_code=rejection_reasons.get(
                    accepted.detail, 'UNCLASSIFIED_RESULT'
                ),
            )
            return result
        self.display_pub.publish(String(data='RETURN' if return_mode else goal.destination_code))
        self.active_goal = goal
        self._publish_event(goal, TaskEvent.EVENT_STARTED, accepted.detail)
        self._publish_navigation(goal, accepted)
        outside = self._outside_map()
        if outside:
            failed = self.workflow.nav_result(succeeded=False, stationary=True)
            self._publish_navigation(goal, failed)
            self._publish_event(
                goal, TaskEvent.EVENT_FAILED, outside,
                reason_code='MAP_POSE_INVALID',
            )
            self.get_logger().error(outside)
            goal_handle.abort(); result.success = False; result.code = ExecuteTransport.Result.CODE_NAVIGATION_FAILED; result.message = outside
            return result
        if not self.nav_client.wait_for_server(timeout_sec=2.0):
            failed = self.workflow.nav_result(succeeded=False, stationary=False)
            self._publish_navigation(goal, failed)
            self._publish_event(
                goal, TaskEvent.EVENT_FAILED, 'NavigateToPose is unavailable',
                reason_code='NAV2_CONTROLLER_FAILED',
            )
            goal_handle.abort(); result.success = False; result.code = ExecuteTransport.Result.CODE_NAVIGATION_FAILED; result.message = 'NavigateToPose is unavailable'
            return result
        # 협로 도크면 Nav2 는 **존 진입점까지만** 데려간다. 통로 안은 규칙 주행이
        # 맡는다 — 통과 여유 0.03 m 에 AMCL 오차 0.08~0.11 m 라 Nav2 로는 못 지난다.
        narrow_zone = approach.profile
        nav_goal = NavigateToPose.Goal()
        nav_goal.pose = copy.deepcopy(goal.dropoff_pose)
        if narrow_zone is not None:
            nav_goal.pose.header.frame_id = 'map'
            assert approach.nav_target is not None
            entry_x = approach.nav_target.x
            entry_y = approach.nav_target.y
            entry_yaw = approach.nav_target.yaw
            nav_goal.pose.pose.position.x = entry_x
            nav_goal.pose.pose.position.y = entry_y
            nav_goal.pose.pose.orientation.x = 0.0
            nav_goal.pose.pose.orientation.y = 0.0
            nav_goal.pose.pose.orientation.z = sin(entry_yaw / 2.0)
            nav_goal.pose.pose.orientation.w = cos(entry_yaw / 2.0)
            self.get_logger().info(
                f'{goal.destination_code}: 협로 존 진입점으로 먼저 간다 '
                f'({entry_x:.3f}, {entry_y:.3f})'
            )
        nav_handle = await self.nav_client.send_goal_async(nav_goal)
        if not nav_handle.accepted:
            failed = self.workflow.nav_result(succeeded=False, stationary=False)
            self._publish_navigation(goal, failed)
            self._publish_event(
                goal, TaskEvent.EVENT_FAILED, 'NavigateToPose rejected the goal',
                reason_code='NAV2_ABORTED',
            )
            goal_handle.abort(); result.success = False; result.code = ExecuteTransport.Result.CODE_NAVIGATION_FAILED; result.message = 'NavigateToPose rejected the goal'
            return result
        self.nav_goal_handles[context.command_id] = nav_handle
        if goal_handle.is_cancel_requested:
            nav_handle.cancel_goal_async()
        nav_result = await nav_handle.get_result_async()
        self.nav_goal_handles.pop(context.command_id, None)
        if goal_handle.is_cancel_requested:
            canceled = self.workflow.cancel_navigation(context.command_id)
            self.display_pub.publish(String(data=''))
            self._publish_navigation(
                goal,
                canceled,
                state_override=NavigationState.STATE_CANCELED,
                detail_override='navigation canceled',
            )
            self._publish_event(
                goal, TaskEvent.EVENT_CANCELED, 'navigation canceled',
                reason_code='RMF_TASK_CANCELLED')
            goal_handle.canceled()
            result.success = False
            result.code = ExecuteTransport.Result.CODE_CANCELED
            result.message = 'navigation canceled'
            result.completed_at = self.get_clock().now().to_msg()
            return result
        # 진입점에 닿았으면 규칙 주행으로 통로를 지난다. Nav2 가 실패했으면 하지 않는다 —
        # 엉뚱한 자리에서 후진하는 것이 가만히 있는 것보다 나쁘다.
        narrow_detail = ''
        if narrow_zone is not None and nav_result.status == 4:
            if narrow_zone.marker_id is not None:
                ran, narrow_detail = await self._run_marker_dock(
                    narrow_zone.marker_id, goal
                )
            else:
                ran, narrow_detail = await self._run_narrow_controller(
                    NarrowZoneController(
                        narrow_zone,
                        direction=ENTER,
                        limits=self._narrow_limits(),
                        calibration=calibration,
                    ),
                    goal_handle,
                )
            if not ran:
                self._publish_event(
                    goal, TaskEvent.EVENT_FAILED, narrow_detail,
                    reason_code='NAV2_ABORTED',
                )
                goal_handle.abort()
                result.success = False
                result.code = ExecuteTransport.Result.CODE_NAVIGATION_FAILED
                result.message = narrow_detail
                result.completed_at = self.get_clock().now().to_msg()
                return result
            # **바구니가 로봇팔에 닿는 자리인가.** 규칙 주행에는 되먹임이 없어
            # 시퀀스가 "다 했다" 고 해도 그 자리가 도크라는 보장이 없다. 도크의 실측
            # 좌표·방향과 대조하는 것이 유일한 근거다. 방향이 틀리면 바구니가 반대쪽을
            # 본다 — 자리가 맞아도 팔이 물건을 넣지 못한다.
            docked, distance, yaw_error = self._verify_narrow_target(
                narrow_zone.dock_target
            )
            self.get_logger().info(
                f'{goal.destination_code}: 협로 진입 후 도크와 거리 {distance:.3f} m, '
                f'yaw 차 {yaw_error:.3f} rad'
            )
            if not docked:
                self._publish_event(
                    goal, TaskEvent.EVENT_FAILED,
                    f'협로 진입 후 도크가 아니다 (거리 {distance:.3f} m, yaw {yaw_error:.3f} rad)',
                    reason_code='GOAL_TOLERANCE_NOT_MET',
                )
                goal_handle.abort()
                result.success = False
                result.code = ExecuteTransport.Result.CODE_NAVIGATION_FAILED
                result.message = '협로 진입 후 도크 자세 불일치'
                result.completed_at = self.get_clock().now().to_msg()
                return result
        precise = not goal.requires_precise_stop or self._at_precise_goal(goal)
        # Nav2 는 goal tolerance 안에 들어오면 SUCCEEDED 를 주고 속도 0 을 요구하지
        # 않는다. 여기서 정차를 기다리지 않으면 workflow 가 "waiting for stop" 을
        # 돌려주고 phase 가 NAVIGATING 에 갇혀, 이후 모든 명령이 "robot is not
        # idle" 로 거절된다. `await` 로 양보하므로 그 사이 odom 콜백이 계속 돌아
        # `self.stationary` 가 갱신된다.
        await self._settle_before_arrival()
        arrived = self.workflow.nav_result(succeeded=nav_result.status == 4 and precise, stationary=self.stationary)
        if arrived.phase is JobPhase.HEALTH_CHECK:
            arrived = self.workflow.finish_return(health_ok=self.recovery_health_ok, cargo_present=False)
        self._publish_navigation(goal, arrived)
        if transport_arrival_succeeded(arrived):
            self._publish_event(goal, TaskEvent.EVENT_ARRIVED, arrived.detail)
            if arrived.phase is JobPhase.WAITING_HANDOVER:
                self._publish_handover(goal, HandoverState.STATE_READY, 'arrived and waiting for handover')
            goal_handle.succeed()
            result.success = True
            result.code = ExecuteTransport.Result.CODE_OK
            result.message = arrived.detail
        else:
            self.display_pub.publish(String(data=''))
            reason_code = (
                'GOAL_TOLERANCE_NOT_MET'
                if nav_result.status == 4 and not precise
                else 'ROBOT_NOT_STOPPED'
                if arrived.detail == 'waiting for stop'
                else 'NAV2_ABORTED'
            )
            self._publish_event(
                goal, TaskEvent.EVENT_FAILED, arrived.detail, reason_code=reason_code
            )
            if reason_code == 'ROBOT_NOT_STOPPED':
                # 상한까지 기다렸는데도 정차 판정이 안 났다. `nav_result` 는
                # phase 를 NAVIGATING 에 남기고 다시 묻는 경로가 없으므로, 여기서
                # 놓아 주지 않으면 이후 모든 명령이 "robot is not idle" 로
                # 거절된다 — 대기를 넣은 것이 확률만 낮춘 셈이 된다.
                #
                # 다른 두 사유는 놓아 줄 필요가 없다. `nav_result(succeeded=False)`
                # 가 이미 phase 를 IDLE 로 내린다.
                self.workflow.cancel_navigation(context.command_id)
            goal_handle.abort(); result.success = False; result.code = ExecuteTransport.Result.CODE_NAVIGATION_FAILED; result.message = arrived.detail
        result.completed_at = self.get_clock().now().to_msg()
        return result

    def _recovery_pose(self) -> PoseStamped:
        message = PoseStamped()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = 'map'
        if self.map_pose is not None:
            x_m, y_m, yaw_rad = self.map_pose
            message.pose.position.x = x_m
            message.pose.position.y = y_m
            message.pose.orientation.z = sin(yaw_rad / 2.0)
            message.pose.orientation.w = cos(yaw_rad / 2.0)
        return message

    async def _run_recovery_nav_action(self, client: ActionClient, goal: object) -> bool:
        if not client.wait_for_server(timeout_sec=2.0):
            return False
        handle = await client.send_goal_async(goal)
        if not handle.accepted:
            return False
        self.recovery_nav_goal_handle = handle
        outcome = await handle.get_result_async()
        self.recovery_nav_goal_handle = None
        return outcome.status == 4

    async def _execute_recovery(self, goal_handle: object) -> ExecuteRecovery.Result:
        """Execute only the bounded action already bound to an operator approval."""
        goal = goal_handle.request
        result = ExecuteRecovery.Result()
        result.pre_pose = self._recovery_pose()
        clearance_before = self.nearest_lidar_range_m
        block = recovery_admission_block_reason(
            goal,
            robot_id=self.robot_id,
            map_revision=self.map_revision,
            ready=self.ready,
            recovery_health_ok=self.recovery_health_ok,
            safety_available=self.safety_seen,
            emergency=self.emergency,
            stationary=self.stationary,
            transport_active=self.workflow.phase is not JobPhase.IDLE or self.recovery_active,
        )
        if block is not None:
            goal_handle.abort()
            result.success = False
            result.code = ExecuteRecovery.Result.CODE_REJECTED
            result.status = 'rejected'
            result.detail = block
            result.post_pose = self._recovery_pose()
            result.clearance_before_m = (
                clearance_before if clearance_before is not None else -1.0
            )
            result.clearance_after_m = result.clearance_before_m
            result.safety_intervened = self.emergency
            result.terminal = True
            return result

        started_ns = self.get_clock().now().nanoseconds
        self.recovery_active = True
        self.recovery_cancel_requested = False
        succeeded = False
        try:
            coord = goal.canonical_coord
            if goal.selected_skill_id == ExecuteRecovery.Goal.SKILL_WAIT_REOBSERVE:
                nav_goal = Wait.Goal()
                nav_goal.time = _duration(1.0)
                succeeded = await self._run_recovery_nav_action(self.wait_client, nav_goal)
            elif goal.selected_skill_id == ExecuteRecovery.Goal.SKILL_BACKUP:
                nav_goal = BackUp.Goal()
                nav_goal.target.x = -abs(float(coord.x))
                nav_goal.speed = 0.03
                nav_goal.time_allowance = _duration(10.0)
                succeeded = await self._run_recovery_nav_action(self.backup_client, nav_goal)
            elif goal.selected_skill_id in (
                ExecuteRecovery.Goal.SKILL_REROUTE_LEFT,
                ExecuteRecovery.Goal.SKILL_REROUTE_RIGHT,
            ):
                heading = atan2(float(coord.y), float(coord.x))
                spin_goal = Spin.Goal()
                spin_goal.target_yaw = heading
                spin_goal.time_allowance = _duration(10.0)
                spun = await self._run_recovery_nav_action(self.spin_client, spin_goal)
                if spun:
                    drive_goal = DriveOnHeading.Goal()
                    drive_goal.target.x = hypot(float(coord.x), float(coord.y))
                    drive_goal.speed = 0.03
                    drive_goal.time_allowance = _duration(10.0)
                    succeeded = await self._run_recovery_nav_action(self.drive_client, drive_goal)
            elif goal.selected_skill_id == ExecuteRecovery.Goal.SKILL_REJOIN and goal.has_map_target:
                nav_goal = NavigateToPose.Goal()
                nav_goal.pose = copy.deepcopy(goal.map_target)
                succeeded = await self._run_recovery_nav_action(self.nav_client, nav_goal)
        finally:
            self.recovery_active = False

        result.post_pose = self._recovery_pose()
        # EN: -1 is explicit "not observed"; it must never be treated as safe clearance.
        # KO: -1은 "관측되지 않음"이며 안전한 여유 거리로 해석하면 안 된다.
        result.clearance_before_m = clearance_before if clearance_before is not None else -1.0
        result.clearance_after_m = (
            self.nearest_lidar_range_m if self.nearest_lidar_range_m is not None else -1.0
        )
        result.elapsed_seconds = (
            self.get_clock().now().nanoseconds - started_ns
        ) / 1_000_000_000
        result.safety_intervened = self.emergency
        result.terminal = True
        if self.recovery_cancel_requested:
            goal_handle.canceled()
            result.success = False
            result.code = ExecuteRecovery.Result.CODE_CANCELED
            result.status = 'cancelled'
            result.detail = 'approved recovery cancelled'
        elif succeeded and not self.emergency:
            goal_handle.succeed()
            result.success = True
            result.code = ExecuteRecovery.Result.CODE_OK
            result.status = 'succeeded'
            result.detail = 'approved recovery completed'
        else:
            goal_handle.abort()
            result.success = False
            result.code = (
                ExecuteRecovery.Result.CODE_SAFETY_VETO
                if self.emergency else ExecuteRecovery.Result.CODE_NAV2_FAILED
            )
            result.status = 'failed'
            result.detail = 'Safety veto' if self.emergency else 'Nav2 recovery action failed'
        return result

    def _cancel_recovery(self, _: object) -> CancelResponse:
        """Propagate cancellation to the currently executing Nav2 behavior."""
        self.recovery_cancel_requested = True
        if self.recovery_nav_goal_handle is not None:
            self.recovery_nav_goal_handle.cancel_goal_async()
        return CancelResponse.ACCEPT

    def _cancel(self, goal_handle: object) -> CancelResponse:
        """RMF stop을 현재 Nav2 goal 취소로 전달한다."""
        command_id = goal_handle.request.task_context.command_id
        self.workflow.cancel_navigation(command_id)
        nav_goal_handle = self.nav_goal_handles.get(command_id)
        if nav_goal_handle is not None:
            nav_goal_handle.cancel_goal_async()
        return CancelResponse.ACCEPT

    def _publish_navigation(
        self,
        goal: ExecuteTransport.Goal,
        outcome: object,
        *,
        state_override: int | None = None,
        detail_override: str = '',
    ) -> None:
        message = NavigationState(); message.stamp = self.get_clock().now().to_msg(); message.robot_id = self.robot_id
        message.task_context = goal.task_context
        message.state = state_override if state_override is not None else (NavigationState.STATE_ACTIVE if outcome.phase is JobPhase.NAVIGATING else NavigationState.STATE_SUCCEEDED if outcome.phase in (JobPhase.WAITING_HANDOVER, JobPhase.IDLE) else NavigationState.STATE_FAILED)
        message.target_pose = goal.dropoff_pose; message.detail = detail_override or outcome.detail
        self.navigation_pub.publish(message)

    async def _settle_before_arrival(self) -> None:
        """정차하거나 상한에 닿을 때까지 기다린다. 판정은 `arrival` 이 한다."""
        timeout_s = float(self.get_parameter('arrival_stop_timeout_s').value)
        started_ns = self.get_clock().now().nanoseconds
        while True:
            waited_s = (self.get_clock().now().nanoseconds - started_ns) / 1e9
            if may_report_arrival(
                stationary=self.stationary, waited_s=waited_s, timeout_s=timeout_s
            ):
                return
            await self._sleep(0.05)

    def _sleep(self, seconds: float) -> Future:
        """executor 에 `seconds` 만큼 양보한다. 그 사이 odom 콜백이 계속 돈다.

        `asyncio.sleep` 은 쓸 수 없다. rclpy executor 는 asyncio 이벤트 루프를
        돌리지 않고 `coro.send(None)` 으로 코루틴을 직접 밀며
        (`rclpy/task.py` `Task._execute_coroutine_step`), 받아 주는 yield 값은
        `Future` 와 `None` 둘뿐이다. `asyncio.sleep(delay)` 는 `delay > 0` 이면
        `get_running_loop()` 를 먼저 부르므로 `RuntimeError: no running event loop`
        로 죽는다. 하필 로봇이 감쇠 중일 때만 그 자리에 닿으므로, 고치려던 레이스
        에서만 터져 정상으로 보인다.

        `None` 을 yield 해 다음 spin 에 재개하는 방법도 rclpy 는 받아 주지만,
        그러면 상한(기본 2초)까지 executor 를 바쁘게 돌린다. 이 PC 는 12코어에
        GPU 가 없어 부하가 이미 제약이므로 timer 로 실제 간격을 둔다.

        clock 은 노드 것을 쓴다 — `use_sim_time` 이면 timer 도 시뮬 시계를 따르므로
        `_settle_before_arrival` 의 경과 계산과 같은 시계가 된다.

        timer 정리는 `add_done_callback` 에 맡긴다. 발화 콜백 안에서 `timer` 를
        참조하면 `create_timer` 가 돌아오기 전에 발화하는 경우 아직 이름이 묶이지
        않아 `NameError` 가 난다. 완료 콜백은 `timer` 가 확실히 묶인 뒤에 등록되고,
        이미 완료된 Future 에도 rclpy 가 즉시 불러 준다.
        """
        future = Future()
        timer = self.create_timer(seconds, lambda: _complete_once(future))
        future.add_done_callback(lambda _: self.destroy_timer(timer))
        return future

    def _verify_narrow_target(self, target: Pose2D | None) -> tuple[bool, float, float]:
        """규칙 진입/탈출 완료 pose를 실측 target과 비교한다."""
        if self.map_pose is None or self.map_frame != 'map' or target is None:
            return False, float('inf'), float('inf')
        return verify_pose(
            self.map_pose,
            (target.x, target.y, target.yaw),
            xy_tolerance_m=PRECISE_STOP_XY_TOLERANCE_M,
            yaw_tolerance_rad=PRECISE_STOP_YAW_TOLERANCE_RAD,
        )

    def _on_map(self, message: OccupancyGrid) -> None:
        """정적 지도의 실제 범위를 기억한다."""
        info = message.info
        x0 = info.origin.position.x
        y0 = info.origin.position.y
        self.map_bounds = (
            x0, y0,
            x0 + info.width * info.resolution,
            y0 + info.height * info.resolution,
        )

    def _outside_map(self) -> str:
        """지도 밖이면 사람이 읽을 이유를, 안이면 빈 문자열을 준다.

        지도 밖으로 나가면 NavFn 이 `Start Coordinates ... was outside bounds` 로
        **모든** 계획을 거절한다. 그대로 두면 RMF 가 영원히 재시도해 로그만 쌓이고
        로봇은 서 있다. 여기서 한 번에 끊고 무엇이 잘못됐는지 말한다.
        """
        if self.map_bounds is None or self.map_pose is None or self.map_frame != 'map':
            return ''
        x0, y0, x1, y1 = self.map_bounds
        x, y, _ = self.map_pose
        if x0 <= x <= x1 and y0 <= y <= y1:
            return ''
        return (
            f'로봇이 지도 밖에 있습니다: 자세 ({x:.2f}, {y:.2f}), '
            f'지도 x {x0:.2f}~{x1:.2f} y {y0:.2f}~{y1:.2f}. '
            '수동으로 지도 안으로 옮기고 초기 위치를 다시 잡아야 합니다.'
        )

    def _load_narrow_zones(self) -> dict:
        """협로 catalog를 읽는다. disabled 항목도 남겨 Nav2 폴백을 막는다.

        지도 이름이 맞지 않으면 **적재하지 않는다.** 값이 그 지도 좌표계에 묶여 있어,
        다른 지도에서 쓰면 로봇이 엉뚱한 자리에서 후진한다.
        """
        path = str(self.get_parameter('narrow_zones_file').value or '').strip()
        map_name_for_warning = str(self.get_parameter('narrow_map_name').value or '').strip()
        if not path:
            # 빈 값은 "이 지도에 표가 없다"는 뜻이다. 조용히 넘어가면 로봇이 협로에
            # Nav2 로 들어가려다 갇히고, 로그에는 아무 단서도 남지 않는다.
            self.get_logger().warning(
                f"협로 존 표가 없어 규칙 주행을 끕니다 (지도 '{map_name_for_warning}'). "
                f"config/narrow_zones.{map_name_for_warning}.yaml 을 만들면 켜집니다."
            )
            return {}
        map_name = str(self.get_parameter('narrow_map_name').value or '').strip()
        try:
            document = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
            zones = load_narrow_zones(document, map_name=map_name)
        except (OSError, yaml.YAMLError, NarrowZoneConfigError) as error:
            # 조용히 넘어가면 로봇이 협로에 Nav2 로 들어가려다 갇힌다. 크게 남긴다.
            self.get_logger().error(f'협로 존 표를 쓸 수 없습니다: {error}')
            return {}
        self.get_logger().info(
            f'협로 profile {len(zones)}개 적재 '
            f'(운영 가능 {sum(profile.executable for profile in zones.values())}개): '
            f'{", ".join(sorted(zones))}'
        )
        return zones

    def _stop_narrow_drive(self) -> None:
        self.narrow_cmd_pub.publish(Twist())

    async def _run_marker_dock(self, marker_id: str, transport_goal) -> tuple[bool, str]:
        """ArUco action server가 정렬·180도 회전·후진을 모두 끝낼 때까지 기다린다."""
        if not self.dock_client.wait_for_server(timeout_sec=2.0):
            return False, 'marker dock action server가 없다'
        request = Dock.Goal()
        request.job_id = transport_goal.task_context.job_id
        request.job_step_id = transport_goal.task_context.command_id
        request.marker_id = marker_id
        handle = await self.dock_client.send_goal_async(request)
        if not handle.accepted:
            return False, f'ArUco marker {marker_id} 도킹 요청이 거절됐다'
        wrapped = await handle.get_result_async()
        dock_result = wrapped.result
        if not dock_result.success:
            return False, f'ArUco 도킹 실패({dock_result.code}): {dock_result.message}'
        return True, dock_result.message

    @staticmethod
    def _narrow_limits() -> MotionLimits:
        return MotionLimits(
            max_linear_mps=NARROW_MAX_LINEAR_MPS,
            max_angular_rps=NARROW_MAX_ANGULAR_RPS,
            linear_tolerance_m=NARROW_POSITION_TOLERANCE_M,
            angular_tolerance_rad=NARROW_YAW_TOLERANCE_RAD,
            step_timeout_s=NARROW_STEP_TIMEOUT_S,
        )

    async def _run_narrow_controller(
        self, controller: NarrowZoneController, goal_handle: object
    ) -> tuple[bool, str]:
        """한 번의 진입/탈출을 실행하고 모든 terminal 경로에서 0 속도를 보낸다."""
        label = controller.direction
        if self.map_pose is None:
            self._stop_narrow_drive()
            return False, 'map pose 를 모른다'
        now_s = self.get_clock().now().nanoseconds / 1e9
        if not controller.begin(Pose2D(*self.map_pose), now_s=now_s):
            self._stop_narrow_drive()
            return False, str(controller.failure)

        while not controller.is_complete:
            if goal_handle.is_cancel_requested:
                controller.cancel('navigation canceled')
            elif self.emergency:
                controller.cancel('안전 정지')
            elif self.map_pose is None:
                controller.cancel('map pose 를 잃었다')
            if controller.failure is not None:
                self._stop_narrow_drive()
                return False, controller.failure

            current = Pose2D(*self.map_pose)
            now_s = self.get_clock().now().nanoseconds / 1e9
            command_value = controller.advance(current, now_s=now_s)
            if controller.failure is not None:
                self._stop_narrow_drive()
                return False, controller.failure
            message = Twist()
            message.linear.x = command_value.linear_x
            message.angular.z = command_value.angular_z
            self.narrow_cmd_pub.publish(message)
            await self._sleep(0.05)

        self._stop_narrow_drive()
        return True, f'협로 {label} 완료'

    def _at_precise_goal(self, goal: ExecuteTransport.Goal) -> bool:
        # 목표는 map 프레임이다(`protocol.py` 가 'map' 을 박는다). odom pose 와
        # 비교하면 spawn 오프셋과 드리프트만큼 언제나 어긋나 dock 도착이 구조적으로
        # 실패한다 — 2026-08-19 실측에서 y 가 0.61 m 벌어져 허용오차 0.05 m 를
        # 넘겼고 step 이 GOAL_TOLERANCE_NOT_MET 으로 죽었다.
        #
        # frame_id 가 map 이 아니면 판정하지 않는다. AMCL 수렴 전에는 로봇이 자기
        # 위치를 map 으로 말할 수 없고, 그때 통과시키면 엉뚱한 자리에서 인계가 열린다.
        if self.map_pose is None or self.map_frame != "map":
            _warn(self, 
                '정밀 정차 판정 불가: map_pose=%s map_frame=%s (destination=%s)'
                % (self.map_pose, self.map_frame, getattr(goal, 'destination_code', '?'))
            )
            return False
        orientation = goal.dropoff_pose.pose.orientation
        yaw = atan2(2 * (orientation.w * orientation.z + orientation.x * orientation.y), 1 - 2 * (orientation.y * orientation.y + orientation.z * orientation.z))
        target = goal.dropoff_pose.pose.position
        ok = within_tolerance(
            current=self.map_pose,
            target=(target.x, target.y, yaw),
            xy_tolerance_m=PRECISE_STOP_XY_TOLERANCE_M,
            yaw_tolerance_rad=PRECISE_STOP_YAW_TOLERANCE_RAD,
        )
        if not ok:
            # 무엇과 무엇을 비교해 떨어졌는지 남긴다. 이것이 없으면 원장에는
            # `GOAL_TOLERANCE_NOT_MET` 만 남아, 허용오차가 좁은 것인지 애초에
            # 다른 구간의 목표와 비교한 것인지 구별할 수 없다.
            _warn(self, 
                '정밀 정차 실패 destination=%s 목표=(%.3f, %.3f, yaw %.3f) '
                '현재=(%.3f, %.3f, yaw %.3f) 거리=%.3f m yaw차=%.3f rad '
                '허용=(%.3f m, %.3f rad)'
                % (
                    getattr(goal, 'destination_code', '?'),
                    target.x, target.y, yaw,
                    self.map_pose[0], self.map_pose[1], self.map_pose[2],
                    ((self.map_pose[0] - target.x) ** 2 + (self.map_pose[1] - target.y) ** 2) ** 0.5,
                    abs(atan2(sin(self.map_pose[2] - yaw), cos(self.map_pose[2] - yaw))),
                    PRECISE_STOP_XY_TOLERANCE_M, PRECISE_STOP_YAW_TOLERANCE_RAD,
                )
            )
        return ok

    def _publish_event(
        self,
        goal: ExecuteTransport.Goal,
        event_type: int,
        detail: str,
        *,
        reason_code: str = '',
    ) -> None:
        reason_codes = {
            TaskEvent.EVENT_STARTED: 'COMMAND_ACCEPTED',
            TaskEvent.EVENT_ARRIVED: 'WAYPOINT_REACHED',
            TaskEvent.EVENT_CANCELED: 'NAVIGATION_CANCELED',
            TaskEvent.EVENT_FAILED: 'NAVIGATION_FAILED',
        }
        event = TaskEvent(); event.stamp = self.get_clock().now().to_msg(); event.event_id = str(uuid4())
        event.robot_id = self.robot_id; event.task_context = goal.task_context
        event.event_type = event_type
        event.reason_code = reason_code or reason_codes[event_type]
        event.method_code = 'NAV2_DEFAULT'; event.detail = detail
        self.event_pub.publish(event)

    def _publish_handover(self, source: object, state: int, detail: str) -> None:
        message = HandoverState(); message.stamp = self.get_clock().now().to_msg(); message.robot_id = self.robot_id
        context = getattr(source, 'task_context', None)
        message.job_id = str(context.job_id) if context is not None else source.job_id
        message.job_step_id = str(context.job_step_id) if context is not None else getattr(source, 'job_step_id', '')
        message.station_id = getattr(source, 'dropoff_location_id', ''); message.state = state; message.detail = detail
        self.handover_pub.publish(message)


def main() -> None:
    rclpy.init(); node = FleetNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node(); rclpy.shutdown()
