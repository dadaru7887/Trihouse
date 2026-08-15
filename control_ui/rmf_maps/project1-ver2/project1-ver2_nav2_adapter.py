#!/usr/bin/env python3
"""project1-ver2 프로젝트의 RMF ↔ Nav2 어댑터.

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
import time
import uuid

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
from rmf_dispenser_msgs.msg import DispenserRequest, DispenserRequestItem, DispenserResult
from rclpy.qos import QoSProfile, QoSDurabilityPolicy, QoSReliabilityPolicy
from std_msgs.msg import String as StringMsg
import tf2_ros

# 진행 상황을 내보내는 자리. 앱이 이것을 읽어 단계를 넘긴다.
#
# RMF 의 작업 상태는 rmf-web 의 웹소켓으로만 나간다. 웹서버를 띄우지 않으면
# 어디에서도 볼 수 없다. 그런데 목적지를 하나씩 받는 것은 이 어댑터이므로,
# 여기가 진행을 아는 가장 이른 자리다.
PROGRESS_TOPIC = 'project1_pinky/task_progress'
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
    'pinky_01': 'pinky_01',
    'pinky_02': 'pinky_02',
}

# 건물 층 이름. nav graph 의 level 과 같아야 한다.
MAP_NAME = 'L1'


def yaw_of(rotation):
    """사원수에서 yaw 를 푼다. 평면을 도는 로봇이라 이것 하나면 된다."""
    x, y, z, w = rotation.x, rotation.y, rotation.z, rotation.w
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


class RobotAdapter:
    """로봇 한 대. RMF 쪽과 Nav2 쪽을 양쪽으로 붙인다."""

    next_registration_at = 0.0

    def __init__(self, name, namespace, node, tf_buffer, fleet_handle,
                 fleet_config, registration_delay):
        self.name = name
        self.namespace = namespace
        self.node = node
        self.tf_buffer = tf_buffer
        self.fleet_handle = fleet_handle
        self.fleet_config = fleet_config
        self.update_handle = None
        self.update_ready_at = None
        self.execution = None
        self.goal_handle = None
        # Nav2 액션 결과는 비동기로 늦게 돌아온다. 새 목적지가 옛 목적지를
        # 선점한 뒤 옛 취소 결과가 도착해도 현재 RMF 실행을 끝내면 안 된다.
        self.goal_generation = 0
        self.warned = False
        self.lock = threading.Lock()
        self.nav = ActionClient(
            node, NavigateToPose, f'/{namespace}/navigate_to_pose')
        request_qos = QoSProfile(
            depth=10,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.dispenser_requests = node.create_publisher(
            DispenserRequest, '/dispenser_requests', request_qos)
        self.dispenser_result_subscription = node.create_subscription(
            DispenserResult, '/dispenser_results',
            self.on_dispenser_result, 10)
        self.dispenser_execution = None
        self.dispenser_request_guid = None
        self.dispenser_target_guid = None
        # pybind C++가 콜백을 사용하는 동안 Python 객체가 회수되지 않게 한다.
        self.callbacks = self.make_callbacks()

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
            self.goal_generation += 1
            generation = self.goal_generation
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
            self.finish(generation, execution)
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
        future.add_done_callback(
            lambda done: self.on_goal_response(done, generation, execution))

    def on_goal_response(self, future, generation, execution):
        handle = future.result()
        if handle is None or not handle.accepted:
            with self.lock:
                current = generation == self.goal_generation
            if not current:
                return
            self.node.get_logger().error(f'[{self.name}] Nav2 가 거절했습니다.')
            self.finish(generation, execution)
            return
        with self.lock:
            if generation != self.goal_generation:
                handle.cancel_goal_async()
                return
            self.goal_handle = handle
        handle.get_result_async().add_done_callback(
            lambda done: self.on_goal_result(done, generation, execution))

    def on_goal_result(self, future, generation, execution):
        # 결과를 봐야 한다. 안 보고 끝났다고 알리면 RMF 는 그 자리에 닿은 줄
        # 알고 다음 단계로 넘어간다 — 픽업에 가지도 않았는데 드랍오프로 가는
        # 것이 이것 때문이었다.
        status = getattr(future.result(), 'status', None)
        ok = status == GoalStatus.STATUS_SUCCEEDED
        with self.lock:
            # 새 목표가 이 목표를 선점했다. Nav2의 CANCELED/ABORTED는 옛 목표의
            # 결과이지 현재 RMF 실행의 실패가 아니다.
            if generation != self.goal_generation:
                return
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
        self.finish(generation, execution)

    def finish(self, generation, execution):
        """RMF 에 이 명령이 끝났다고 알린다."""
        with self.lock:
            if (generation != self.goal_generation or
                    self.execution is not execution):
                return
            self.execution = None
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
            self.goal_generation += 1
            self.execution = None
            self.goal_handle = None
            if self.dispenser_execution is execution:
                self.dispenser_execution = None
                self.dispenser_request_guid = None
                self.dispenser_target_guid = None

    def execute_action(self, category, description, execution):
        """armLoad 를 해당 픽업 자리의 RMF 워크셀 요청으로 바꾼다."""
        seconds = 1.0
        target_guid = None
        item_type = 'policy_1'
        quantity = 1
        if isinstance(description, dict):
            target_guid = description.get('target_guid')
            item_type = str(description.get('item_type') or 'policy_1')
            quantity = max(1, int(description.get('quantity') or 1))
            for key, scale in (('seconds', 1.0),
                               ('unix_millis_action_duration_estimate',
                                0.001)):
                value = description.get(key)
                if isinstance(value, (int, float)) and value > 0:
                    seconds = float(value) * scale
                    break
        if category != 'armLoad' or not target_guid:
            self.node.get_logger().error(
                f'[{self.name}] 동작 [{category}]에 워크셀 위치가 없습니다.')
            report(robot=self.name, event='action_failed', category=category)
            execution.finished()
            return

        request_guid = f'{self.name}-{uuid.uuid4()}'
        with self.lock:
            self.execution = execution
            self.dispenser_execution = execution
            self.dispenser_request_guid = request_guid
            self.dispenser_target_guid = str(target_guid)
        self.node.get_logger().info(
            f'[{self.name}] 동작 [{category}] → 워크셀 [{target_guid}] 요청 '
            f'({request_guid})')
        report(robot=self.name, event='action_start',
               category=category, seconds=seconds)
        request = DispenserRequest()
        request.time = self.node.get_clock().now().to_msg()
        request.request_guid = request_guid
        request.target_guid = str(target_guid)
        request.transporter_type = self.name
        item = DispenserRequestItem()
        item.type_guid = item_type
        item.quantity = quantity
        item.compartment_name = 'pinky_tray'
        request.items = [item]
        self.dispenser_requests.publish(request)

    def on_dispenser_result(self, result):
        with self.lock:
            if (result.request_guid != self.dispenser_request_guid or
                    self.dispenser_execution is None):
                return
            if result.status == DispenserResult.ACKNOWLEDGED:
                self.node.get_logger().info(
                    f'[{self.name}] 워크셀 [{self.dispenser_target_guid}]이 '
                    '요청을 받았습니다.')
                return
            if result.status != DispenserResult.SUCCESS:
                self.node.get_logger().error(
                    f'[{self.name}] 워크셀 요청 실패 (status={result.status})')
                return
            execution = self.dispenser_execution
            target = self.dispenser_target_guid
            self.dispenser_execution = None
            self.dispenser_request_guid = None
            self.dispenser_target_guid = None
            if self.execution is execution:
                self.execution = None
        self.node.get_logger().info(
            f'[{self.name}] 워크셀 [{target}] 동작 완료.')
        report(robot=self.name, event='action_done', category='armLoad')
        execution.finished()

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
            if time.monotonic() < RobotAdapter.next_registration_at:
                return
            # 처음 자리를 알게 된 순간에 RMF 에 등록한다. 자리를 모르는 채로
            # 넣으면 RMF 가 그 로봇을 어디에 둘지 모른다.
            handle = self.fleet_handle.add_robot(
                self.name, state,
                self.fleet_config.get_known_robot_configuration(self.name),
                self.callbacks)
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
            RobotAdapter.next_registration_at = time.monotonic() + 3.0
            # add_robot의 C++ 측 등록 완료 콜백이 끝나기 전에 update()를 호출하면
            # Jazzy rmf_adapter가 SIGSEGV를 낸다. wall clock으로 여유를 둔다.
            self.update_ready_at = time.monotonic() + 2.0
            self.warned = False
            self.node.get_logger().info(f'[{self.name}] RMF 에 붙었습니다.')
            return
        if (self.update_ready_at is not None and
                time.monotonic() < self.update_ready_at):
            return
        with self.lock:
            activity = (
                self.execution.identifier if self.execution is not None else None)
        self.update_handle.update(state, activity)


def main(argv=sys.argv):
    rclpy.init(args=argv)
    rmf_adapter.init_rclcpp()
    parser = argparse.ArgumentParser(prog='project1_pinky' + '_nav2_adapter')
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
    time.sleep(1.0)

    tf_buffer = tf2_ros.Buffer()
    tf2_ros.TransformListener(tf_buffer, node)

    fleet_handle = adapter.add_easy_fleet(fleet_config)

    robots = []
    for index, name in enumerate(fleet_config.known_robots):
        namespace = ROBOT_NAMESPACES.get(name)
        if namespace is None:
            node.get_logger().warn(
                f'[{name}] 의 ROS 네임스페이스를 모릅니다. 건너뜁니다.')
            continue
        robots.append(
            RobotAdapter(
                name, namespace, node, tf_buffer, fleet_handle, fleet_config,
                index * 3.0))

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
