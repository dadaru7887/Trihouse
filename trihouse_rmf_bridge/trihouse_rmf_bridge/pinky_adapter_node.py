"""Pinky RobotStatus/ExecuteTransport와 Open-RMF EasyFullControl 연결."""

from __future__ import annotations

import argparse
import math
import sys
from threading import Lock
from typing import Any

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.parameter import Parameter

import rmf_adapter
from rmf_adapter import Adapter
import rmf_adapter.easy_full_control as rmf_easy

from trihouse_interfaces.action import ExecuteTransport
from trihouse_interfaces.msg import RobotStatus

from .execution import ExecutionRegistry
from .fms_client import CommandClaimError, FmsCommandClaimClient
from .state import PinkyState


def _yaw_of(rotation: Any) -> float:
    x = float(rotation.x)
    y = float(rotation.y)
    z = float(rotation.z)
    w = float(rotation.w)
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


class PinkyRobotAdapter:
    """RMF robot 하나와 Pinky action server 하나를 연결한다."""

    def __init__(
        self,
        *,
        node: Node,
        fleet_handle: Any,
        robot_name: str,
        rmf_map_name: str,
        charger_waypoint: str,
        status_topic: str,
        transport_action: str,
        map_revision: str,
        status_timeout_s: float,
        fms_base_url: str,
        fms_timeout_s: float,
    ) -> None:
        self._node = node
        self._fleet_handle = fleet_handle
        self._robot_name = robot_name
        self._rmf_map_name = rmf_map_name
        self._charger_waypoint = charger_waypoint
        self._map_revision = map_revision
        self._status_timeout_ns = int(status_timeout_s * 1_000_000_000)

        self._lock = Lock()
        self._latest_state: PinkyState | None = None
        self._update_handle: Any | None = None
        self._decommissioned = False
        self._last_invalid_reason = ""
        self._last_rejected_frame = ""
        self._registry = ExecutionRegistry()
        self._command_claims = FmsCommandClaimClient(
            fms_base_url, timeout_s=fms_timeout_s,
        )
        self._executions: dict[str, Any] = {}
        self._goal_handles: dict[str, Any] = {}

        self._transport = ActionClient(node, ExecuteTransport, transport_action)
        self._status_subscription = node.create_subscription(
            RobotStatus, status_topic, self._on_status, 10
        )

    def callbacks(self) -> Any:
        return rmf_easy.RobotCallbacks(
            self._navigate,
            self._stop,
            self._execute_action,
        )

    def _on_status(self, message: RobotStatus) -> None:
        if message.robot_id != self._robot_name:
            return
        if message.frame_id != "map":
            if message.frame_id != self._last_rejected_frame:
                self._node.get_logger().warning(
                    f"[{self._robot_name}] RMF pose 갱신 거절: "
                    f"frame_id={message.frame_id or '<empty>'}, expected=map"
                )
                self._last_rejected_frame = message.frame_id
            return
        self._last_rejected_frame = ""
        pose = message.pose.pose
        received_at_ns = self._node.get_clock().now().nanoseconds
        state = PinkyState(
            robot_id=message.robot_id,
            map_name=self._rmf_map_name,
            x=float(pose.position.x),
            y=float(pose.position.y),
            yaw=_yaw_of(pose.orientation),
            battery_percentage=float(message.battery_percentage),
            ready=bool(message.dispatchable),
            observed_at_ns=received_at_ns,
        )
        with self._lock:
            self._latest_state = state

    def update(self) -> None:
        """최신 실측 상태만 RMF에 등록하거나 갱신한다."""
        now_ns = self._node.get_clock().now().nanoseconds
        with self._lock:
            state = self._latest_state
            update_handle = self._update_handle

        if state is None:
            return

        validation = state.validate(now_ns, self._status_timeout_ns)
        if not validation.accepted:
            if update_handle is not None and not self._decommissioned:
                more = update_handle.more()
                more.unstable_decommission()
                more.override_status("error")
                more.log_error(validation.reason_code)
                self._decommissioned = True
            if validation.reason_code != self._last_invalid_reason:
                self._node.get_logger().warning(
                    f"[{self._robot_name}] RMF 상태 갱신 중단: "
                    f"{validation.reason_code}"
                )
                self._last_invalid_reason = validation.reason_code
            return

        rmf_state = rmf_easy.RobotState(
            state.map_name,
            list(state.rmf_position),
            state.rmf_soc,
        )

        if update_handle is None:
            chargers = [self._charger_waypoint] if self._charger_waypoint else []
            update_handle = self._fleet_handle.add_robot(
                self._robot_name,
                rmf_state,
                rmf_easy.RobotConfiguration(chargers),
                self.callbacks(),
            )
            if update_handle is None:
                self._node.get_logger().warning(
                    f"[{self._robot_name}] 현재 위치를 navigation graph에 "
                    "병합하지 못해 RMF 등록을 재시도합니다."
                )
                return
            with self._lock:
                self._update_handle = update_handle
            self._node.get_logger().info(
                f"[{self._robot_name}] 유효한 pose/SOC로 RMF에 등록했습니다."
            )

        if self._decommissioned:
            more = update_handle.more()
            more.unstable_recommission()
            more.override_status(None)
            more.log_info("Pinky telemetry recovered")
            self._decommissioned = False
            self._node.get_logger().info(
                f"[{self._robot_name}] 상태 복구 확인 후 RMF에 recommission했습니다."
            )

        self._last_invalid_reason = ""
        update_handle.update(rmf_state, self._registry.current_activity())

    def _navigate(self, destination: Any, execution: Any) -> None:
        with self._lock:
            update_handle = self._update_handle
        rmf_task_id = ""
        if update_handle is not None:
            rmf_task_id = str(update_handle.more().current_task_id() or "")

        # 실행할 수 없는 것을 원장에 먼저 적지 않는다. `claim` 은 Gateway 에
        # 명령 행과 시도 행을 남기는 부수효과다. 확인을 뒤에 두면 실패해도 흔적이
        # 남고, RMF 가 재시도할 때마다 그 흔적이 쌓인다.
        if not self._transport.server_is_ready():
            self._fail_without_finish(
                "Pinky ExecuteTransport action server가 없습니다."
            )
            return

        position = list(destination.position)
        if len(position) != 3 or not all(math.isfinite(float(v)) for v in position):
            self._fail_without_finish("RMF 목적지 pose가 유효하지 않습니다.")
            return

        try:
            context = self._command_claims.claim(
                rmf_task_id=rmf_task_id,
                robot_id=self._robot_name,
                execution_id=str(execution.identifier),
                map_revision=self._map_revision,
            )
        except CommandClaimError as error:
            self._fail_without_finish(str(error))
            return

        command_id = context.command_id
        decision = self._registry.start(execution.identifier, command_id)
        if not decision.accepted:
            self._fail_without_finish("RMF execution 또는 command ID가 없습니다.")
            return

        if decision.replaced_command_id:
            self._cancel_command(decision.replaced_command_id)

        with self._lock:
            self._executions[command_id] = execution

        goal = ExecuteTransport.Goal()
        goal.task_context.active = context.active
        goal.task_context.job_id = context.job_id
        goal.task_context.job_step_id = context.job_step_id
        goal.task_context.assignment_revision = context.assignment_revision
        goal.task_context.rmf_task_id = context.rmf_task_id
        goal.task_context.command_id = context.command_id
        goal.task_context.map_revision = context.map_revision
        goal.task_context.command_source = context.command_source
        destination_name = str(getattr(destination, "name", "") or "")
        goal.dropoff_location_id = destination_name
        goal.destination_code = destination_name or "RMF"
        goal.dropoff_pose.header.frame_id = "map"
        goal.dropoff_pose.header.stamp = self._node.get_clock().now().to_msg()
        goal.dropoff_pose.pose.position.x = float(position[0])
        goal.dropoff_pose.pose.position.y = float(position[1])
        goal.dropoff_pose.pose.orientation.z = math.sin(float(position[2]) / 2.0)
        goal.dropoff_pose.pose.orientation.w = math.cos(float(position[2]) / 2.0)
        goal.priority = 0
        goal.requires_precise_stop = bool(getattr(destination, "dock", None))
        goal.mode = ExecuteTransport.Goal.MODE_RMF_NAVIGATION

        self._node.get_logger().info(
            f"[{self._robot_name}] RMF {context.rmf_task_id} -> "
            f"({position[0]:.3f}, {position[1]:.3f}, {position[2]:.3f})"
        )
        future = self._transport.send_goal_async(goal)
        future.add_done_callback(
            lambda completed, cid=command_id: self._on_goal_response(cid, completed)
        )

    def _on_goal_response(self, command_id: str, future: Any) -> None:
        try:
            goal_handle = future.result()
        except Exception as error:  # rclpy future transports the original exception
            self._fail_command(command_id, f"Pinky goal 전송 실패: {error}")
            return

        if goal_handle is None or not goal_handle.accepted:
            self._fail_command(command_id, "Pinky가 RMF 이동 goal을 거절했습니다.")
            return

        if self._registry.current_command_id() != command_id:
            goal_handle.cancel_goal_async()
            return

        with self._lock:
            self._goal_handles[command_id] = goal_handle
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            lambda completed, cid=command_id: self._on_goal_result(cid, completed)
        )

    def _on_goal_result(self, command_id: str, future: Any) -> None:
        with self._lock:
            self._goal_handles.pop(command_id, None)
            execution = self._executions.pop(command_id, None)

        try:
            wrapped_result = future.result()
            result = wrapped_result.result
            succeeded = bool(result.success)
            detail = str(result.message)
        except Exception as error:
            succeeded = False
            detail = f"Pinky action 결과 수신 실패: {error}"

        finish = self._registry.finish(command_id)
        if not finish.should_finish_rmf or execution is None:
            return

        if succeeded:
            if self._update_handle is not None:
                self._update_handle.more().override_status(None)
            execution.finished()
            self._node.get_logger().info(
                f"[{self._robot_name}] Pinky 도착·정지 확인 후 RMF 이동을 완료했습니다."
            )
            return

        self._fail_without_finish(detail or "Pinky RMF 이동이 실패했습니다.")

    def _stop(self, activity: Any) -> None:
        decision = self._registry.stop(activity)
        if not decision.should_cancel_pinky:
            return
        self._cancel_command(decision.command_id)
        self._node.get_logger().info(
            f"[{self._robot_name}] RMF stop을 Pinky action cancel로 전달했습니다."
        )

    def _cancel_command(self, command_id: str) -> None:
        with self._lock:
            goal_handle = self._goal_handles.pop(command_id, None)
            self._executions.pop(command_id, None)
        if goal_handle is not None:
            goal_handle.cancel_goal_async()

    def _fail_command(self, command_id: str, detail: str) -> None:
        with self._lock:
            self._goal_handles.pop(command_id, None)
            self._executions.pop(command_id, None)
        finish = self._registry.finish(command_id)
        if finish.should_finish_rmf:
            self._fail_without_finish(detail)

    def _fail_without_finish(self, detail: str) -> None:
        self._node.get_logger().error(f"[{self._robot_name}] {detail}")
        if self._update_handle is not None:
            more = self._update_handle.more()
            more.override_status("error")
            more.log_error(detail)
            more.replan()

    def _execute_action(self, category: str, description: Any, execution: Any) -> None:
        self._node.get_logger().error(
            f"[{self._robot_name}] 지원하지 않는 RMF action category: {category}"
        )
        if self._update_handle is not None:
            more = self._update_handle.more()
            more.log_error(f"Unsupported action category: {category}")
            more.replan()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pinky_easy_fleet_adapter",
        description="Pinky ExecuteTransport용 Open-RMF EasyFullControl adapter",
    )
    parser.add_argument("-c", "--config-file", required=True)
    parser.add_argument("-n", "--nav-graph", required=True)
    parser.add_argument("--robot-name", default="")
    parser.add_argument("--rmf-map-name", default="L1")
    parser.add_argument("--charger-waypoint", default="충전1")
    parser.add_argument("--status-topic", default="/trihouse/status")
    parser.add_argument("--transport-action", default="/trihouse/transport/execute")
    parser.add_argument("--map-revision", required=True)
    parser.add_argument("--status-timeout", type=float, default=3.0)
    parser.add_argument("--fms-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--fms-timeout", type=float, default=2.0)
    parser.add_argument("--use-sim-time", action="store_true")
    return parser.parse_args(rclpy.utilities.remove_ros_args(argv)[1:])


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv if argv is None else argv)
    args = _parse_args(argv)
    rclpy.init(args=argv)
    rmf_adapter.init_rclcpp()

    fleet_config = rmf_easy.FleetConfiguration.from_config_files(
        args.config_file, args.nav_graph
    )
    if fleet_config is None:
        raise RuntimeError(
            f"RMF fleet config 또는 navigation graph를 읽지 못했습니다: "
            f"{args.config_file}, {args.nav_graph}"
        )

    known_robots = list(fleet_config.known_robots)
    robot_name = args.robot_name
    if not robot_name:
        if len(known_robots) != 1:
            raise RuntimeError(
                "--robot-name을 생략하려면 fleet config에 로봇이 정확히 한 대여야 합니다."
            )
        robot_name = known_robots[0]
    if robot_name not in known_robots:
        raise RuntimeError(f"fleet config에 없는 RMF robot입니다: {robot_name}")

    ros_robot_name = robot_name.replace("-", "_")
    node = Node(f"{fleet_config.fleet_name}_{ros_robot_name}_pinky_adapter")
    adapter = Adapter.make(f"{fleet_config.fleet_name}_fleet_adapter")
    if adapter is None:
        raise RuntimeError(
            "RMF adapter를 만들지 못했습니다. rmf_traffic_schedule_primary를 확인하세요."
        )

    if args.use_sim_time:
        node.set_parameters([Parameter("use_sim_time", value=True)])
        adapter.node.use_sim_time()

    adapter.start()
    fleet_handle = adapter.add_easy_fleet(fleet_config)
    robot = PinkyRobotAdapter(
        node=node,
        fleet_handle=fleet_handle,
        robot_name=robot_name,
        rmf_map_name=args.rmf_map_name,
        charger_waypoint=args.charger_waypoint,
        status_topic=args.status_topic,
        transport_action=args.transport_action,
        map_revision=args.map_revision,
        status_timeout_s=args.status_timeout,
        fms_base_url=args.fms_base_url,
        fms_timeout_s=args.fms_timeout,
    )
    period = max(0.1, fleet_config.update_interval.total_seconds())
    node.create_timer(period, robot.update)
    node.get_logger().info(
        f"{robot_name} EasyFullControl adapter 시작: "
        f"status={args.status_topic}, action={args.transport_action}, "
        f"period={period:.2f}s"
    )

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        adapter.stop()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
