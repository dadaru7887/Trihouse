"""Pinky 운반 요청을 Nav2 action으로 바꾸는 단일 소유 adapter."""

import rclpy
from math import atan2
from uuid import uuid4
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient, ActionServer
from rclpy.action import CancelResponse
from rclpy.node import Node
from std_msgs.msg import Bool, String
from trihouse_interfaces.action import ExecuteTransport
from trihouse_interfaces.msg import CargoState, HandoverState, NavigationState, Readiness, RobotHealth, SafetyState, TaskEvent

from .workflow import JobCommand, JobPhase, TransportWorkflow
from .arrival import within_tolerance


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
        self.robot_id = self.get_parameter('robot_id').value
        self.workflow = TransportWorkflow(robot_id=self.robot_id, expected_map_revision=self.get_parameter('map_revision').value)
        self.ready = False; self.outbox_ready = False; self.cargo_confirmed = False; self.emergency = False; self.stationary = False; self.recovery_health_ok = False; self.current_pose: tuple[float, float, float] | None = None
        self.navigation_pub = self.create_publisher(NavigationState, '/trihouse/navigation/state', 10)
        self.event_pub = self.create_publisher(TaskEvent, '/trihouse/task/events', 10)
        self.handover_pub = self.create_publisher(HandoverState, '/trihouse/handover/state', 10)
        self.display_pub = self.create_publisher(String, '/trihouse/display/destination_code', 10)
        self.create_subscription(Readiness, '/trihouse/readiness', self._on_readiness, 10)
        self.create_subscription(CargoState, '/trihouse/cargo/state', self._on_cargo, 10)
        self.create_subscription(SafetyState, '/trihouse/safety/state', self._on_safety, 10)
        self.create_subscription(RobotHealth, '/trihouse/health', self._on_health, 10)
        self.create_subscription(
            Bool, '/trihouse/fms/event_outbox_ready', self._on_outbox_ready, 10
        )
        self.create_subscription(Odometry, '/odom', self._on_odom, 10)
        self.nav_client = ActionClient(self, NavigateToPose, '/navigate_to_pose')
        self.nav_goal_handles = {}
        self.server = ActionServer(
            self,
            ExecuteTransport,
            '/trihouse/transport/execute',
            self._execute,
            cancel_callback=self._cancel,
        )

    def _on_readiness(self, message: Readiness) -> None:
        self.ready = message.state == Readiness.STATE_READY

    def _on_cargo(self, message: CargoState) -> None:
        self.cargo_confirmed = message.state == CargoState.STATE_LOCKED and message.sensor_confirmed
        if message.state == CargoState.STATE_UNLOCKED and self.workflow.phase is JobPhase.WAITING_HANDOVER:
            completed = self.workflow.complete_handover()
            self.display_pub.publish(String(data=''))
            self._publish_handover(message, HandoverState.STATE_CONFIRMED, completed.detail)

    def _on_safety(self, message: SafetyState) -> None:
        self.emergency = message.state == SafetyState.STATE_EMERGENCY
        if self.emergency:
            self.workflow.enter_emergency(message.detail)

    def _on_health(self, message: RobotHealth) -> None:
        self.recovery_health_ok = message.state == RobotHealth.STATE_OK

    def _on_outbox_ready(self, message: Bool) -> None:
        self.outbox_ready = bool(message.data)

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
        if self.workflow.phase is JobPhase.WAITING_HANDOVER and not return_mode:
            accepted = self.workflow.reassign(context.command_id, context.map_revision)
        else:
            accepted = self.workflow.accept(
                JobCommand(
                    context.command_id,
                    context.job_id,
                    context.map_revision,
                    destination_kind,
                    requires_cargo=not (return_mode or rmf_navigation),
                ),
                ready=self.ready and not self.emergency,
                cargo_confirmed=self.cargo_confirmed,
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
        if not self.nav_client.wait_for_server(timeout_sec=2.0):
            failed = self.workflow.nav_result(succeeded=False, stationary=False)
            self._publish_navigation(goal, failed)
            self._publish_event(
                goal, TaskEvent.EVENT_FAILED, 'NavigateToPose is unavailable',
                reason_code='NAV2_CONTROLLER_FAILED',
            )
            goal_handle.abort(); result.success = False; result.code = ExecuteTransport.Result.CODE_NAVIGATION_FAILED; result.message = 'NavigateToPose is unavailable'
            return result
        nav_goal = NavigateToPose.Goal(); nav_goal.pose = goal.dropoff_pose
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
        precise = not goal.requires_precise_stop or self._at_precise_goal(goal)
        arrived = self.workflow.nav_result(succeeded=nav_result.status == 4 and precise, stationary=self.stationary)
        if arrived.phase is JobPhase.HEALTH_CHECK:
            arrived = self.workflow.finish_return(health_ok=self.recovery_health_ok, cargo_present=self.cargo_confirmed)
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
            self._publish_event(
                goal, TaskEvent.EVENT_FAILED, arrived.detail,
                reason_code=(
                    'GOAL_TOLERANCE_NOT_MET'
                    if nav_result.status == 4 and not precise
                    else 'ROBOT_NOT_STOPPED'
                    if arrived.detail == 'waiting for stop'
                    else 'NAV2_ABORTED'
                ),
            )
            goal_handle.abort(); result.success = False; result.code = ExecuteTransport.Result.CODE_NAVIGATION_FAILED; result.message = arrived.detail
        result.completed_at = self.get_clock().now().to_msg()
        return result

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

    def _at_precise_goal(self, goal: ExecuteTransport.Goal) -> bool:
        if self.current_pose is None:
            return False
        orientation = goal.dropoff_pose.pose.orientation
        yaw = atan2(2 * (orientation.w * orientation.z + orientation.x * orientation.y), 1 - 2 * (orientation.y * orientation.y + orientation.z * orientation.z))
        target = goal.dropoff_pose.pose.position
        return within_tolerance(current=self.current_pose, target=(target.x, target.y, yaw), xy_tolerance_m=0.05, yaw_tolerance_rad=0.0873)

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
