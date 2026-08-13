#!/usr/bin/env python3
"""Nav2 behavior_server의 NavigateToPose action을 감싸는 래퍼. mission_runner.py가
waypoint 사이 이동을 시킬 때 이 노드의 `_call_navigate_to_pose()`를 호출한다.

**주의: 실행 전 반드시 확인할 것**
  1. Nav2가 떠있어야 함: ros2 launch pinky_navigation bringup_launch.xml
  2. action 정확한 필드명은 실제 설치된 nav2_msgs 버전으로 재확인 권장:
       ros2 interface show nav2_msgs/action/NavigateToPose
     (이 파일은 ROS2 Jazzy 표준 nav2_msgs 기준으로 작성했으나, 반드시 위 명령어로
     필드명 대조 후 사용할 것)

원래 이 파일은 VLM/RL 쪽 recovery skill(BACKUP/REROUTE_LEFT/REROUTE_RIGHT/WAIT_REOBSERVE/
REJOIN)까지 Nav2 action으로 실행하는 더 큰 버전이었으나, driving_fms(FMS 프로토타입,
VLM/RL 미포함)에서는 NavigateToPose 하나만 실제로 쓰여서 그 부분만 남기고 트리밍함.
"""

from __future__ import annotations

import math

import rclpy
import tf2_ros
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.time import Time
from sensor_msgs.msg import LaserScan


def yaw_to_quaternion(yaw: float) -> tuple[float, float, float, float]:
    """yaw(rad) -> (x,y,z,w) quaternion, roll=pitch=0 가정(지면 위 로봇이므로)."""
    return (0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0))


class NavRecoveryExecutor(Node):
    """mission_runner.py의 MissionRunner가 이 노드로 NavigateToPose를 호출하고,
    _get_pos()/_last_scan_min_range로 현재 위치/라이다 최소거리를 읽는다."""

    def __init__(self) -> None:
        super().__init__("nav_recovery_executor")

        self.navigate_client = ActionClient(self, NavigateToPose, "navigate_to_pose")

        self._last_odom: Odometry | None = None
        self._last_scan_min_range: float = float("inf")
        self.create_subscription(Odometry, "/odom", self._on_odom, 10)
        self.create_subscription(LaserScan, "/scan", self._on_scan, 10)

        # pre_pos/post_pos 등은 map 프레임 nominal waypoint 기준으로 비교돼야 하는데
        # /odom은 odom 프레임이라 그대로 쓰면 안 됨 -- TF(map->base_footprint) 우선.
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        self.get_logger().info("nav_recovery_executor 기동 -- navigate_to_pose action client 준비됨")

    def _on_odom(self, msg: Odometry) -> None:
        self._last_odom = msg

    def _on_scan(self, msg: LaserScan) -> None:
        valid = [r for r in msg.ranges if msg.range_min < r < msg.range_max]
        self._last_scan_min_range = min(valid) if valid else float("inf")

    def _get_pos(self) -> tuple[float, float]:
        """map 프레임 (x,y). TF(map->base_footprint)를 우선 쓰고, 아직 못 받았으면
        (초기 짧은 구간만) /odom으로 fallback -- fallback 시 map 프레임이 아니라서
        거리 계산이 부정확할 수 있음을 호출부가 감안해야 함."""
        try:
            tf = self.tf_buffer.lookup_transform("map", "base_footprint", Time())
            return (tf.transform.translation.x, tf.transform.translation.y)
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException,
                tf2_ros.ExtrapolationException):
            pass
        if self._last_odom is None:
            return (0.0, 0.0)
        p = self._last_odom.pose.pose.position
        return (p.x, p.y)

    def _send_and_wait(self, client: ActionClient, goal_msg, timeout_sec: float) -> bool:
        if not client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error(f"{client._action_name} action server 없음 -- Nav2 떠있는지 확인 필요")
            return False

        send_future = client.send_goal_async(goal_msg)
        try:
            rclpy.spin_until_future_complete(self, send_future, timeout_sec=timeout_sec)
        except KeyboardInterrupt:
            # goal_handle을 아직 못 받은 시점 -- 서버가 이미 accept했을 가능성은 있지만
            # 로컬에서 취소할 방법이 없음(핸들 없이는 cancel 요청 자체가 불가). 그대로
            # 재전파해서 호출부가 중단을 알게 함 (아래 result_future 쪽이 실제 위험 구간).
            self.get_logger().warn(f"{client._action_name} 전송 중 Ctrl+C -- 핸들 없이 중단")
            raise
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().warn(f"{client._action_name} goal 거부됨")
            return False

        result_future = goal_handle.get_result_async()
        try:
            rclpy.spin_until_future_complete(self, result_future, timeout_sec=timeout_sec)
        except KeyboardInterrupt:
            # 안전 패치: 로봇이 실제로 움직이는 중(goal accepted, 결과 대기)에 Ctrl+C가
            # 들어온 경우. 여기서 그냥 raise하면 로봇이 스크립트 종료 후에도 계속 움직이는
            # 사고가 재현됨 -- 반드시 취소 요청을 보내고 완료까지 기다린 뒤 재전파.
            self.get_logger().warn(f"{client._action_name} Ctrl+C -- goal 취소 요청 중")
            cancel_future = goal_handle.cancel_goal_async()
            rclpy.spin_until_future_complete(self, cancel_future, timeout_sec=5.0)
            self.get_logger().warn(f"{client._action_name} Ctrl+C -- goal 취소 완료(또는 시도함), 정지됨")
            raise
        result = result_future.result()
        if result is None:
            # 안전 버그 수정: 여기서 그냥 return하면 우리 쪽은 "타임아웃"으로 포기하지만
            # Nav2 서버 쪽 goal은 취소된 적이 없어서 계속 살아서 재시도를 무한 반복함 --
            # 실측으로 확인된 실제 사고(스크립트는 끝났는데 로봇이 계속 움직임). 반드시
            # 명시적으로 취소하고, 취소 자체도 완료될 때까지 잠깐 기다려서 확실히 정지시킨다.
            self.get_logger().warn(f"{client._action_name} timeout -- goal 취소 요청 중")
            cancel_future = goal_handle.cancel_goal_async()
            rclpy.spin_until_future_complete(self, cancel_future, timeout_sec=5.0)
            self.get_logger().warn(f"{client._action_name} timeout -- goal 취소 완료(또는 시도함)")
            return False
        # status는 우리 쪽 goal 상태(action_msgs/GoalStatus)일 뿐이라 "왜" 실패했는지는
        # 안 알려줌 -- behavior_server 자체 로그(Nav2 콘솔)를 봐야 진짜 이유(충돌감지 등)를
        # 알 수 있지만, 최소한 실패했다는 사실과 status 코드는 여기 남겨서 나중에 추적 가능하게 함.
        STATUS_NAMES = {0: "UNKNOWN", 1: "ACCEPTED", 2: "EXECUTING", 3: "CANCELING",
                         4: "SUCCEEDED", 5: "CANCELED", 6: "ABORTED"}
        if result.status != GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().warn(
                f"{client._action_name} 실패: status={STATUS_NAMES.get(result.status, result.status)} "
                f"-- 상세 원인은 Nav2 behavior_server 콘솔 로그 확인 필요")
        return result.status == GoalStatus.STATUS_SUCCEEDED

    def _call_navigate_to_pose(self, x: float, y: float, yaw: float, timeout_sec: float) -> bool:
        goal = NavigateToPose.Goal()
        pose = PoseStamped()
        pose.header.frame_id = "map"
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x = float(x)
        pose.pose.position.y = float(y)
        qx, qy, qz, qw = yaw_to_quaternion(float(yaw))
        pose.pose.orientation.x, pose.pose.orientation.y = qx, qy
        pose.pose.orientation.z, pose.pose.orientation.w = qz, qw
        goal.pose = pose
        return self._send_and_wait(self.navigate_client, goal, timeout_sec)


if __name__ == "__main__":
    print("이 파일은 직접 실행하는 게 아니라 mission_runner.py에서 import해서 씁니다.")
    print("\n실행 전 필수 확인:")
    print("  1. ros2 launch pinky_navigation bringup_launch.xml (Nav2 기동)")
    print("  2. ros2 interface show nav2_msgs/action/NavigateToPose 로 필드명 실제 확인")
    print("  3. 로봇이 실제로 움직일 수 있으니 충분한 공간에서, 감독 하에 첫 실행할 것")
