"""ArUco 정렬→180도 회전→협로 후진을 제공하는 ROS 2 Dock action server."""

from __future__ import annotations

import math
from pathlib import Path

import rclpy
import tf2_ros
from geometry_msgs.msg import Twist
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.node import Node
from rclpy.task import Future
from trihouse_interfaces.action import Dock
from trihouse_interfaces.msg import MarkerObservation, Readiness

from .marker_controller import (
    ALIGNING,
    REVERSING,
    SEARCHING,
    TURNING,
    DockCommand,
    MarkerDockController,
    MarkerSample,
)
from .marker_profiles import MarkerProfileError, load_marker_profiles


FEEDBACK_STATE = {
    SEARCHING: Dock.Feedback.STATE_SEARCHING,
    ALIGNING: Dock.Feedback.STATE_ALIGNING,
    TURNING: Dock.Feedback.STATE_ALIGNING,
    REVERSING: Dock.Feedback.STATE_APPROACHING,
}


def yaw_from_quaternion(q) -> float:
    return math.atan2(
        2.0 * (q.w * q.z + q.x * q.y),
        1.0 - 2.0 * (q.y * q.y + q.z * q.z),
    )


class MarkerDockNode(Node):
    def __init__(self) -> None:
        super().__init__("marker_dock")
        self.declare_parameter("profiles_file", "")
        self.declare_parameter("map_name", "")
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("odom_frame", "odom")
        self.declare_parameter("base_frame", "base_footprint")
        self.declare_parameter("control_period_s", 0.05)

        profiles_file = str(self.get_parameter("profiles_file").value).strip()
        map_name = str(self.get_parameter("map_name").value).strip()
        if not profiles_file or not map_name:
            raise RuntimeError("profiles_file과 map_name 파라미터가 필요합니다")
        try:
            by_destination = load_marker_profiles(Path(profiles_file), map_name=map_name)
        except (OSError, MarkerProfileError) as error:
            raise RuntimeError(f"마커 도킹 표를 적재할 수 없습니다: {error}") from error
        self.profiles = {profile.marker_id: profile for profile in by_destination.values()}
        if len(self.profiles) != len(by_destination):
            raise RuntimeError("서로 다른 도크가 같은 marker_id를 사용한다")

        self.odom_frame = str(self.get_parameter("odom_frame").value)
        self.map_frame = str(self.get_parameter("map_frame").value)
        self.base_frame = str(self.get_parameter("base_frame").value)
        self.vision_ready = False
        self.controller: MarkerDockController | None = None
        self.active_goal = None
        self.completion: Future | None = None

        self.buffer = tf2_ros.Buffer()
        tf2_ros.TransformListener(self.buffer, self)
        self.cmd_pub = self.create_publisher(Twist, "cmd_vel_dock", 10)
        self.create_subscription(
            MarkerObservation,
            "trihouse/vision/marker_observation/base",
            self._on_marker,
            10,
        )
        self.create_subscription(
            Readiness, "trihouse/vision/readiness", self._on_readiness, 10
        )
        self.server = ActionServer(
            self,
            Dock,
            "trihouse/dock",
            self._execute,
            goal_callback=self._accept_goal,
            cancel_callback=self._cancel_goal,
        )
        self.create_timer(float(self.get_parameter("control_period_s").value), self._tick)

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds / 1e9

    def _pose(self) -> tuple[float, float, float] | None:
        try:
            transform = self.buffer.lookup_transform(
                self.odom_frame, self.base_frame, rclpy.time.Time()
            )
        except (
            tf2_ros.LookupException,
            tf2_ros.ConnectivityException,
            tf2_ros.ExtrapolationException,
        ):
            return None
        p = transform.transform.translation
        return p.x, p.y, yaw_from_quaternion(transform.transform.rotation)

    def _map_pose(self) -> tuple[float, float, float] | None:
        try:
            transform = self.buffer.lookup_transform(
                self.map_frame, self.base_frame, rclpy.time.Time()
            )
        except (
            tf2_ros.LookupException,
            tf2_ros.ConnectivityException,
            tf2_ros.ExtrapolationException,
        ):
            return None
        p = transform.transform.translation
        return p.x, p.y, yaw_from_quaternion(transform.transform.rotation)

    def _accept_goal(self, request) -> GoalResponse:
        if self.controller is not None or str(request.marker_id) not in self.profiles:
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _cancel_goal(self, _goal_handle) -> CancelResponse:
        return CancelResponse.ACCEPT

    def _on_readiness(self, message: Readiness) -> None:
        self.vision_ready = message.state == Readiness.STATE_READY

    def _on_marker(self, message: MarkerObservation) -> None:
        if self.controller is None:
            return
        received_at = self._now()
        position = message.pose.pose.position
        self.controller.observe(
            MarkerSample(
                marker_id=str(message.marker_id),
                received_at_s=received_at,
                ttl_s=float(message.ttl_ms) / 1000.0,
                confidence=float(message.confidence),
                forward_m=float(position.x),
                left_m=float(position.y),
            ),
            now_s=received_at,
        )

    async def _execute(self, goal_handle) -> Dock.Result:
        result = Dock.Result()
        profile = self.profiles.get(str(goal_handle.request.marker_id))
        pose = self._pose()
        map_pose = self._map_pose()
        if profile is None or pose is None or map_pose is None:
            goal_handle.abort()
            result.success = False
            result.code = Dock.Result.CODE_TOLERANCE_NOT_REACHED
            result.message = "검증된 marker profile 또는 odom/map TF가 없다"
            return result
        if not profile.allows_activation(map_pose[0], map_pose[1]):
            goal_handle.abort()
            result.success = False
            result.code = Dock.Result.CODE_TOLERANCE_NOT_REACHED
            result.message = "마커 도킹 activation 반경 밖이다"
            return result

        self.controller = MarkerDockController(profile)
        self.controller.begin(now_s=self._now(), pose=pose)
        self.active_goal = goal_handle
        self.completion = Future()
        success, code, message = await self.completion
        self._publish(DockCommand())
        if goal_handle.is_cancel_requested:
            goal_handle.canceled()
        elif success:
            goal_handle.succeed()
        else:
            goal_handle.abort()
        result.success = success
        result.code = code
        result.message = message
        result.completed_at = self.get_clock().now().to_msg()
        self.controller = None
        self.active_goal = None
        self.completion = None
        return result

    def _finish(self, success: bool, code: int, message: str) -> None:
        self._publish(DockCommand())
        if self.completion is not None and not self.completion.done():
            self.completion.set_result((success, code, message))

    def _tick(self) -> None:
        controller, goal = self.controller, self.active_goal
        if controller is None or goal is None:
            return
        if goal.is_cancel_requested:
            controller.abort("canceled")
            self._finish(False, Dock.Result.CODE_CANCELED, "도킹 취소")
            return
        pose = self._pose()
        if pose is None:
            controller.abort("odom_tf_lost")
            self._finish(
                False, Dock.Result.CODE_TOLERANCE_NOT_REACHED, "도킹 중 odom TF 소실"
            )
            return
        command = controller.advance(
            now_s=self._now(), pose=pose, vision_ready=self.vision_ready
        )
        self._publish(command)
        feedback = Dock.Feedback()
        feedback.state = FEEDBACK_STATE.get(controller.state, Dock.Feedback.STATE_VERIFYING)
        feedback.detail = controller.state
        goal.publish_feedback(feedback)
        if controller.is_failed:
            code = (
                Dock.Result.CODE_MARKER_LOST
                if controller.failure in ("vision_not_ready", "searching_timeout", "aligning_timeout")
                else Dock.Result.CODE_TIMEOUT
            )
            self._finish(False, code, str(controller.failure))
        elif controller.is_complete:
            self._finish(True, Dock.Result.CODE_OK, "마커 정렬 후 후진 주차 완료")

    def _publish(self, command: DockCommand) -> None:
        message = Twist()
        message.linear.x = command.linear_x
        message.angular.z = command.angular_z
        self.cmd_pub.publish(message)

    def destroy_node(self):
        self._publish(DockCommand())
        self.server.destroy()
        return super().destroy_node()


def main() -> None:
    rclpy.init()
    node = MarkerDockNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
