#!/usr/bin/env python3
"""recovery_data_collector.py의 execute_and_observe_stub()를 실제 Nav2 behavior_server
action 호출로 교체한 버전. §31에서 확인한 behavior_plugins(spin/backup/drive_on_heading/
wait)와 표준 navigate_to_pose를 skill_id별로 매핑해서 실제로 호출.

**주의: 실행 전 반드시 확인할 것**
  1. Nav2가 떠있어야 함: ros2 launch pinky_navigation bringup_launch.xml
  2. action 정확한 필드명은 실제 설치된 nav2_msgs 버전으로 재확인 권장:
       ros2 interface show nav2_msgs/action/BackUp
       ros2 interface show nav2_msgs/action/Spin
       ros2 interface show nav2_msgs/action/Wait
       ros2 interface show nav2_msgs/action/DriveOnHeading
       ros2 interface show nav2_msgs/action/NavigateToPose
     (이 파일은 ROS2 Jazzy 표준 nav2_msgs 기준으로 작성했으나, 실제 로봇에서 검증 안 됨 --
     반드시 위 명령어로 필드명 대조 후 사용할 것)

skill -> Nav2 action 매핑 (§31):
  BACKUP         -> BackUp action (coord 크기만큼 후진)
  REROUTE_LEFT   -> Spin(양의 각도) + DriveOnHeading
  REROUTE_RIGHT  -> Spin(음의 각도) + DriveOnHeading
  WAIT_REOBSERVE -> Wait action (짧게 대기, 재관찰 목적)
  REJOIN         -> NavigateToPose(coord를 목표 pose로 직접 제출)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import rclpy
import tf2_ros
from action_msgs.msg import GoalStatus
from builtin_interfaces.msg import Duration
from geometry_msgs.msg import Point, PoseStamped
from nav2_msgs.action import BackUp, DriveOnHeading, NavigateToPose, Spin, Wait
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.time import Time
from sensor_msgs.msg import LaserScan

from real_reward import dist_to_goal, is_mission_rejoined, is_terminal_critical

SKILL_NAMES = ["BACKUP", "REROUTE_LEFT", "REROUTE_RIGHT", "WAIT_REOBSERVE", "REJOIN"]
DEFAULT_TIMEOUT_SEC = 15.0
DEFAULT_SPEED = 0.1  # [m/s] -- nav2_params.yaml max_velocity(0.25)보다 보수적으로 낮게


def yaw_to_quaternion(yaw: float) -> tuple[float, float, float, float]:
    """yaw(rad) -> (x,y,z,w) quaternion, roll=pitch=0 가정(지면 위 로봇이므로)."""
    return (0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0))


def seconds_to_duration(sec: float) -> Duration:
    d = Duration()
    d.sec = int(sec)
    d.nanosec = int((sec - int(sec)) * 1e9)
    return d


@dataclass
class ExecutionResult:
    success: bool
    pre_pos: tuple[float, float]
    post_pos: tuple[float, float]
    pre_min_range: float
    post_min_range: float
    elapsed_sec: float


class NavRecoveryExecutor(Node):
    """recovery_data_collector.py에서 이 노드를 만들어서 execute_skill()을
    execute_and_observe_stub() 대신 호출하면 됨."""

    def __init__(self) -> None:
        super().__init__("nav_recovery_executor")

        self.backup_client = ActionClient(self, BackUp, "backup")
        self.spin_client = ActionClient(self, Spin, "spin")
        self.wait_client = ActionClient(self, Wait, "wait")
        self.drive_client = ActionClient(self, DriveOnHeading, "drive_on_heading")
        self.navigate_client = ActionClient(self, NavigateToPose, "navigate_to_pose")

        self._last_odom: Odometry | None = None
        self._last_scan_min_range: float = float("inf")
        self.create_subscription(Odometry, "/odom", self._on_odom, 10)
        self.create_subscription(LaserScan, "/scan", self._on_scan, 10)

        # 2026-08-11: orchestrate_live_teleop.py에서 발견한 것과 같은 종류의 프레임 버그를
        # 여기서도 미리 막음 -- pre_pos/post_pos는 dist_to_goal()(map 프레임 nominal
        # waypoint 기준)에 바로 들어가는데, /odom은 odom 프레임이라 그대로 쓰면 안 됨.
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        self.get_logger().info("nav_recovery_executor 기동 -- backup/spin/wait/drive_on_heading/"
                                "navigate_to_pose action client 준비됨")

    def _on_odom(self, msg: Odometry) -> None:
        self._last_odom = msg

    def _on_scan(self, msg: LaserScan) -> None:
        valid = [r for r in msg.ranges if msg.range_min < r < msg.range_max]
        self._last_scan_min_range = min(valid) if valid else float("inf")

    def _get_pos(self) -> tuple[float, float]:
        """map 프레임 (x,y). TF(map->base_footprint)를 우선 쓰고, 아직 못 받았으면
        (초기 짧은 구간만) /odom으로 fallback -- fallback 시 map 프레임이 아니라서
        dist_to_goal 계산이 부정확할 수 있음을 호출부가 감안해야 함."""
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

    # ------------------------------------------------------------------
    # 개별 action 호출 (동기 대기 -- 짧은 recovery 동작이라 blocking으로 단순화,
    # 실제 배포 시 rclpy.spin_until_future_complete 패턴 유지)
    # ------------------------------------------------------------------

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
            # 2026-08-13 안전 패치: 로봇이 실제로 움직이는 중(goal accepted, 결과 대기)에
            # Ctrl+C가 들어온 경우. 여기서 그냥 raise하면 이전에 겪은 사고(타임아웃 미취소로
            # 로봇이 스크립트 종료 후에도 계속 움직임)와 똑같은 패턴이 Ctrl+C로 재현됨 --
            # 반드시 취소 요청을 보내고 완료까지 기다린 뒤 재전파.
            self.get_logger().warn(f"{client._action_name} Ctrl+C -- goal 취소 요청 중")
            cancel_future = goal_handle.cancel_goal_async()
            rclpy.spin_until_future_complete(self, cancel_future, timeout_sec=5.0)
            self.get_logger().warn(f"{client._action_name} Ctrl+C -- goal 취소 완료(또는 시도함), 정지됨")
            raise
        result = result_future.result()
        if result is None:
            # 2026-08-12 안전 버그 수정: 여기서 그냥 return하면 우리 쪽은 "타임아웃"으로
            # 포기하지만 Nav2 서버 쪽 goal은 취소된 적이 없어서 계속 살아서 재시도(backup->
            # retry->실패->재시도...)를 무한 반복함 -- 실측으로 확인된 실제 사고(스크립트는
            # 끝났는데 로봇이 계속 움직임). 반드시 명시적으로 취소하고, 취소 자체도 완료될
            # 때까지 잠깐 기다려서 확실히 정지시킨다.
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

    def _call_backup(self, dist: float, timeout_sec: float) -> bool:
        goal = BackUp.Goal()
        goal.target = Point(x=-abs(dist), y=0.0, z=0.0)  # 후진이므로 -x
        goal.speed = DEFAULT_SPEED
        goal.time_allowance = seconds_to_duration(timeout_sec)
        return self._send_and_wait(self.backup_client, goal, timeout_sec)

    def _call_spin(self, target_yaw: float, timeout_sec: float) -> bool:
        goal = Spin.Goal()
        goal.target_yaw = float(target_yaw)
        goal.time_allowance = seconds_to_duration(timeout_sec)
        return self._send_and_wait(self.spin_client, goal, timeout_sec)

    def _call_drive_on_heading(self, dist: float, timeout_sec: float) -> bool:
        goal = DriveOnHeading.Goal()
        goal.target = Point(x=abs(dist), y=0.0, z=0.0)
        goal.speed = DEFAULT_SPEED
        goal.time_allowance = seconds_to_duration(timeout_sec)
        return self._send_and_wait(self.drive_client, goal, timeout_sec)

    def _call_wait(self, seconds: float) -> bool:
        goal = Wait.Goal()
        goal.time = seconds_to_duration(seconds)
        return self._send_and_wait(self.wait_client, goal, seconds + 5.0)

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

    # ------------------------------------------------------------------
    # 통합 진입점 -- recovery_data_collector.py의 execute_and_observe_stub() 대체
    # ------------------------------------------------------------------

    def execute_skill(self, skill_id: int, coord, timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> ExecutionResult:
        skill_name = SKILL_NAMES[skill_id]
        pre_pos = self._get_pos()
        pre_min_range = self._last_scan_min_range
        t0 = self.get_clock().now()

        if skill_name == "BACKUP":
            dist = float((coord[0] ** 2 + coord[1] ** 2) ** 0.5)
            success = self._call_backup(dist, timeout_sec)

        elif skill_name in ("REROUTE_LEFT", "REROUTE_RIGHT"):
            sign = 1.0 if skill_name == "REROUTE_LEFT" else -1.0
            spin_ok = self._call_spin(sign * abs(float(coord[2])), timeout_sec / 2)
            drive_ok = self._call_drive_on_heading(float(coord[0]), timeout_sec / 2)
            success = spin_ok and drive_ok

        elif skill_name == "WAIT_REOBSERVE":
            success = self._call_wait(2.0)

        elif skill_name == "REJOIN":
            # 2026-08-11 밤: 원래 NavigateToPose(절대좌표)를 썼는데, envelope이 0.25m로
            # 작은데도 15초(타임아웃 꽉 참)씩 걸리고 실패하는 경우가 실측으로 확인됨(Nav2
            # 풀 플래너+컨트롤러가 이렇게 작은 이동엔 과함 -- 최종 orientation 맞추려고 계속
            # 미세조정하거나 recovery behavior가 끼어드는 것으로 추정, 그 사이 위험 근접
            # 상황(terminal_critical)까지 한 번 발생함). REROUTE와 같은 패턴(Spin+
            # DriveOnHeading, 상대 offset)으로 바꿔서 소요시간을 예측 가능하게 함. coord도
            # 이제 절대좌표가 아니라 다른 skill들과 동일하게 상대 offset(dx,dy,dyaw)으로 받음.
            spin_ok = self._call_spin(float(coord[2]), timeout_sec / 2)
            drive_ok = self._call_drive_on_heading(float(coord[0]), timeout_sec / 2)
            success = spin_ok and drive_ok

        else:
            self.get_logger().error(f"알 수 없는 skill: {skill_name}")
            success = False

        elapsed = (self.get_clock().now() - t0).nanoseconds / 1e9
        post_pos = self._get_pos()
        post_min_range = self._last_scan_min_range

        return ExecutionResult(success=success, pre_pos=pre_pos, post_pos=post_pos,
                                pre_min_range=pre_min_range, post_min_range=post_min_range,
                                elapsed_sec=elapsed)


def execute_and_observe_real(executor: NavRecoveryExecutor, skill: int, coord, pre_state: dict) -> tuple[dict, bool]:
    """recovery_data_collector.py의 execute_and_observe_stub()와 동일한 시그니처.
    사용법: collect_one_episode() 안에서 execute_and_observe_stub(...) 호출을
    이 함수 호출로 바꾸면 됨 (executor는 미리 만들어서 넘겨줌).

    2026-08-11: dist_to_goal/terminal_critical/mission_rejoined은 real_reward.py의
    공용 로직으로 통일함 (예전엔 여기서 따로 계산해서 real_reward.py랑 값이 서로
    달랐음 -- dist_to_goal은 예전엔 pre_state에서 이동거리만큼 빼는 방식(오차 누적 가능,
    goal 위치 자체를 안 씀), terminal_critical 임계값도 0.3m로 서로 달랐음).
    elapsed_sec/intervention_level은 이 모듈이 실제 액션 실행 결과(성공/실패, 소요시간)를
    직접 알고 있어서 그대로 유지 -- real_reward.py는 Safety Supervisor 신호가 따로
    없어서 intervention_level=0.0 고정인데, 여기서는 "액션 자체 실행 성공/실패"를 대신
    쓸 수 있어서 이쪽이 더 근거있는 값."""
    result = executor.execute_skill(skill, coord)

    d_goal = dist_to_goal(result.post_pos[0], result.post_pos[1])
    post_state = dict(pre_state)
    post_state["dist_to_goal"] = d_goal
    post_state["dist_to_obstacle"] = result.post_min_range
    post_state["elapsed_sec"] = result.elapsed_sec
    post_state["intervention_level"] = 0.0 if result.success else 1.0  # 액션 실행 성공/실패 기반
    post_state["mission_rejoined"] = is_mission_rejoined(d_goal)

    terminal_critical = is_terminal_critical(result.post_min_range)
    return post_state, terminal_critical


if __name__ == "__main__":
    print("이 파일은 직접 실행하는 게 아니라, recovery_data_collector.py에서 import해서")
    print("NavRecoveryExecutor를 만들고 execute_and_observe_real()을 execute_and_observe_stub()")
    print("대신 호출하도록 연결하는 모듈입니다.")
    print("\n실행 전 필수 확인:")
    print("  1. ros2 launch pinky_navigation bringup_launch.xml (Nav2 기동)")
    print("  2. ros2 interface show nav2_msgs/action/BackUp 등으로 필드명 실제 확인")
    print("  3. 로봇이 실제로 움직일 수 있으니 충분한 공간에서, 감독 하에 첫 실행할 것")
