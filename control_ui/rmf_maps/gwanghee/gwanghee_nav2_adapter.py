#!/usr/bin/env python3
"""gwanghee 프로젝트의 RMF ↔ Nav2 어댑터.

rmf_control_ui 가 맵 프로젝트에서 생성했다. 손으로 고치면 다음 저장 때
덮어써진다.

RMF 가 주는 목적지를 Nav2 의 NavigateToPose 로 바꾸고, TF 에서 읽은 위치를 RMF 에
되돌린다. rmf_demos_fleet_adapter 는 slotcar 전용이라 우리 핑키에게는 상대가 없다.

이 노드는 실물에서도 그대로 돈다. Nav2 가 아래에서 Gazebo 를 몰든 진짜 모터를
몰든 위쪽은 같기 때문이다.
"""

import argparse
import json
import math
import sys
import threading

import rclpy
import rclpy.node
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.parameter import Parameter

import rmf_adapter
from rmf_adapter import Adapter
import rmf_adapter.easy_full_control as rmf_easy

from action_msgs.msg import GoalStatus
from nav2_msgs.action import NavigateToPose
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import String as StringMsg
import tf2_ros

# 진행 상황을 내보내는 자리. 앱이 이것을 읽어 단계를 넘긴다.
#
# RMF 의 작업 상태는 rmf-web 의 웹소켓으로만 나간다. 웹서버를 띄우지 않으면
# 어디에서도 볼 수 없다. 그런데 목적지를 하나씩 받는 것은 이 어댑터이므로,
# 여기가 진행을 아는 가장 이른 자리다.
PROGRESS_TOPIC = 'gwanghee_pinky/task_progress'
_progress = None


def report(**fields):
    """앱에게 지금 무엇을 하는지 알린다. 없으면 조용히 넘어간다."""
    if _progress is None:
        return
    message = StringMsg()
    message.data = json.dumps(fields, ensure_ascii=False)
    _progress.publish(message)

# RMF 가 아는 이름 -> ROS 네임스페이스.
ROBOT_NAMESPACES = {
    'PK_03': 'pinky_03',
}

# 건물 층 이름. nav graph 의 level 과 같아야 한다.
MAP_NAME = 'L1'


def yaw_of(rotation):
    """사원수에서 yaw 를 푼다. 평면을 도는 로봇이라 이것 하나면 된다."""
    x, y, z, w = rotation.x, rotation.y, rotation.z, rotation.w
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


class RobotAdapter:
    """로봇 한 대. RMF 쪽과 Nav2 쪽을 양쪽으로 붙인다."""

    def __init__(self, name, namespace, node, tf_buffer, fleet_handle):
        self.name = name
        self.namespace = namespace
        self.node = node
        self.tf_buffer = tf_buffer
        self.fleet_handle = fleet_handle
        self.update_handle = None
        self.execution = None
        self.goal_handle = None
        self.warned = False
        self.lock = threading.Lock()
        self.nav = ActionClient(
            node, NavigateToPose, f'/{namespace}/navigate_to_pose')

    # ── RMF 가 부르는 쪽 ────────────────────────────────────────────────

    def make_callbacks(self):
        return rmf_easy.RobotCallbacks(
            lambda destination, execution: self.navigate(destination, execution),
            lambda activity: self.stop(activity),
            lambda category, description, execution: self.execute_action(
                category, description, execution),
        )

    def navigate(self, destination, execution):
        """RMF 가 준 목적지로 Nav2 를 보낸다."""
        with self.lock:
            self.execution = execution
        x, y, yaw = destination.position
        self.node.get_logger().info(
            f'[{self.name}] -> ({x:.3f}, {y:.3f}, {math.degrees(yaw):.0f}도)'
            f' 지도 [{destination.map}]')
        report(robot=self.name, event='navigate_start',
               x=float(x), y=float(y), yaw=float(yaw))

        if not self.nav.wait_for_server(timeout_sec=5.0):
            self.node.get_logger().error(
                f'[{self.name}] Nav2 가 없습니다. '
                f'/{self.namespace}/navigate_to_pose 를 확인하세요.')
            self.finish()
            return

        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.node.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(x)
        goal.pose.pose.position.y = float(y)
        goal.pose.pose.orientation.z = math.sin(yaw / 2)
        goal.pose.pose.orientation.w = math.cos(yaw / 2)

        future = self.nav.send_goal_async(goal)
        future.add_done_callback(self.on_goal_response)

    def on_goal_response(self, future):
        handle = future.result()
        if handle is None or not handle.accepted:
            self.node.get_logger().error(f'[{self.name}] Nav2 가 거절했습니다.')
            self.finish()
            return
        with self.lock:
            self.goal_handle = handle
        handle.get_result_async().add_done_callback(self.on_goal_result)

    def on_goal_result(self, future):
        # 결과를 봐야 한다. 안 보고 끝났다고 알리면 RMF 는 그 자리에 닿은 줄
        # 알고 다음 단계로 넘어간다 — 픽업에 가지도 않았는데 드랍오프로 가는
        # 것이 이것 때문이었다.
        status = getattr(future.result(), 'status', None)
        ok = status == GoalStatus.STATUS_SUCCEEDED
        with self.lock:
            self.goal_handle = None
        if ok:
            self.node.get_logger().info(f'[{self.name}] 도착했습니다.')
            report(robot=self.name, event='navigate_done')
        else:
            self.node.get_logger().error(
                f'[{self.name}] 목적지에 닿지 못했습니다 (Nav2 status '
                f'{status}). 도착 반경이 코스트맵 한 칸보다 촘촘하면 영영 '
                f'못 맞춥니다.')
            report(robot=self.name, event='navigate_failed', status=status)
        self.finish()

    def finish(self):
        """RMF 에 이 명령이 끝났다고 알린다."""
        with self.lock:
            execution = self.execution
            self.execution = None
        if execution is not None:
            execution.finished()

    def stop(self, activity):
        """RMF 가 멈추라고 한다. 지금 가고 있는 것만 멈춘다."""
        with self.lock:
            execution = self.execution
            handle = self.goal_handle
        if execution is None or not execution.identifier.is_same(activity):
            return
        self.node.get_logger().info(f'[{self.name}] 멈춥니다.')
        if handle is not None:
            handle.cancel_goal_async()
        with self.lock:
            self.execution = None
            self.goal_handle = None

    def execute_action(self, category, description, execution):
        """RMF 가 이동이 아닌 단계를 맡길 때 부른다.

        앱의 연속 작업에서 `armLoad` 가 여기로 온다. RMF 는 이 동작이 무엇인지
        모르고, 끝났다고 알려 주는 것은 이쪽 몫이다. 붙잡고만 있으면 작업이
        영영 안 끝난다.

        **아직 매니퓰레이터에게 실제로 시키지는 않는다.** OMX 쪽에 이 요청을
        받는 노드가 없다. 지금은 예상 시간만큼 기다리고 끝났다고 알린다.
        여기가 그 노드를 부를 자리다.
        """
        # RMF 는 안쪽 description 만 넘겨 준다. 바깥의
        # unix_millis_action_duration_estimate 는 여기까지 닿지 않으므로
        # 앱이 안쪽에도 `seconds` 를 적어 준다. 그래도 없으면 1초로 본다 —
        # 5초짜리가 1초 만에 끝난 일이 이것 때문이었다.
        seconds = 1.0
        if isinstance(description, dict):
            for key, scale in (('seconds', 1.0),
                               ('unix_millis_action_duration_estimate',
                                0.001)):
                value = description.get(key)
                if isinstance(value, (int, float)) and value > 0:
                    seconds = float(value) * scale
                    break
        self.node.get_logger().info(
            f'[{self.name}] 동작 [{category}] · {seconds:.1f}초')
        report(robot=self.name, event='action_start',
               category=category, seconds=seconds)

        def done():
            timer.cancel()
            self.node.get_logger().info(f'[{self.name}] 동작 [{category}] 끝.')
            report(robot=self.name, event='action_done', category=category)
            execution.finished()

        timer = self.node.create_timer(seconds, done)

    # ── RMF 에 알리는 쪽 ────────────────────────────────────────────────

    def read_state(self):
        """TF 에서 지금 자리를 읽는다. AMCL 이 map -> odom 을 낸다."""
        try:
            tf = self.tf_buffer.lookup_transform(
                'map', f'{self.namespace}/base_footprint',
                rclpy.time.Time(), timeout=Duration(seconds=0.2))
        except Exception:
            return None
        t = tf.transform.translation
        return rmf_easy.RobotState(
            MAP_NAME,
            [t.x, t.y, yaw_of(tf.transform.rotation)],
            # 시뮬레이터에는 배터리가 없다. 실물로 가면 여기에 진짜 값을 넣는다.
            1.0,
        )

    def update(self):
        state = self.read_state()
        if state is None:
            return
        if self.update_handle is None:
            # 처음 자리를 알게 된 순간에 RMF 에 등록한다. 자리를 모르는 채로
            # 넣으면 RMF 가 그 로봇을 어디에 둘지 모른다.
            handle = self.fleet_handle.add_robot(
                self.name, state,
                rmf_easy.RobotConfiguration([]),
                self.make_callbacks())
            if handle is None:
                # 자리가 nav graph 에서 너무 멀면 RMF 가 받지 않는다. 다음에 다시
                # 해 본다 — AMCL 이 아직 안 잡혔을 수 있다. 같은 말을 0.1초마다
                # 되풀이하면 로그를 못 읽으므로 한 번만 적는다.
                if not self.warned:
                    self.warned = True
                    x, y, _ = state.position
                    self.node.get_logger().warn(
                        f'[{self.name}] 자리 ({x:.2f}, {y:.2f}) 가 nav graph 에서'
                        f' 멀어 RMF 가 받지 않습니다. AMCL 이 잡히면 다시 붙습니다.')
                return
            self.update_handle = handle
            self.warned = False
            self.node.get_logger().info(f'[{self.name}] RMF 에 붙었습니다.')
            return
        with self.lock:
            activity = (
                self.execution.identifier if self.execution is not None else None)
        self.update_handle.update(state, activity)


def main(argv=sys.argv):
    rclpy.init(args=argv)
    rmf_adapter.init_rclcpp()
    parser = argparse.ArgumentParser(prog='gwanghee_pinky' + '_nav2_adapter')
    parser.add_argument('-c', '--config_file', required=True)
    parser.add_argument('-n', '--nav_graph', required=True)
    parser.add_argument('-s', '--use_sim_time', action='store_true')
    args = parser.parse_args(rclpy.utilities.remove_ros_args(argv)[1:])

    fleet_config = rmf_easy.FleetConfiguration.from_config_files(
        args.config_file, args.nav_graph)
    assert fleet_config, f'설정을 읽지 못했습니다: {args.config_file}'

    node = rclpy.node.Node(fleet_config.fleet_name + '_nav2_adapter')
    global _progress
    # 앱이 늦게 붙어도 마지막 소식은 받도록 남겨 둔다.
    _progress = node.create_publisher(StringMsg, PROGRESS_TOPIC, 10)
    adapter = Adapter.make(fleet_config.fleet_name + '_fleet_adapter')
    assert adapter, (
        'fleet adapter 를 만들지 못했습니다. '
        'rmf_traffic_schedule_primary 가 떠 있는지 확인하세요.')

    if args.use_sim_time:
        node.set_parameters(
            [Parameter('use_sim_time', Parameter.Type.BOOL, True)])
        adapter.node.use_sim_time()

    adapter.start()

    tf_buffer = tf2_ros.Buffer()
    tf2_ros.TransformListener(tf_buffer, node)

    fleet_handle = adapter.add_easy_fleet(fleet_config)

    robots = []
    for name in fleet_config.known_robots:
        namespace = ROBOT_NAMESPACES.get(name)
        if namespace is None:
            node.get_logger().warn(
                f'[{name}] 의 ROS 네임스페이스를 모릅니다. 건너뜁니다.')
            continue
        robots.append(
            RobotAdapter(name, namespace, node, tf_buffer, fleet_handle))

    if not robots:
        node.get_logger().error('이을 로봇이 없습니다.')

    period = fleet_config.update_interval.total_seconds()
    node.create_timer(period, lambda: [robot.update() for robot in robots])

    node.get_logger().info(
        f'{fleet_config.fleet_name} 를 Nav2 에 이었습니다. '
        f'로봇 {len(robots)}대, {period:.2f}초마다 알립니다.')

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    adapter.stop()
    # 신호로 끊길 때 rclpy 가 먼저 context 를 닫아 놓는다. 그때 또 부르면
    # 예외가 올라와, 멀쩡히 끝난 것이 죽은 것처럼 보인다.
    if rclpy.ok():
        rclpy.shutdown()


if __name__ == '__main__':
    main(sys.argv)
