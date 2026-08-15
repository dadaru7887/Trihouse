#!/usr/bin/env python3
"""project1 프로젝트의 RMF 워크셀 어댑터.

rmf_control_ui 가 맵 프로젝트에서 생성했다. 손으로 고치면 다음 저장 때
덮어써진다.

로봇이 픽업 자리에 닿으면 RMF 가 `/dispenser_requests` 로 그 자리 이름을
부른다. 여기서 팔을 움직이고 `/dispenser_results` 로 끝났다고 답한다.

답하지 않으면 RMF 는 영원히 기다린다. 오류는 안 난다 — 작업이 그 자리에서
멈춰 있을 뿐이다.
"""

import sys
import threading

import rclpy
import rclpy.node
from rclpy.qos import QoSProfile, QoSDurabilityPolicy, QoSReliabilityPolicy

from builtin_interfaces.msg import Time
from rmf_dispenser_msgs.msg import DispenserRequest, DispenserResult, DispenserState
from rmf_ingestor_msgs.msg import IngestorRequest, IngestorResult, IngestorState
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

# 로봇 ID, ROS 네임스페이스, 맡은 픽업 자리, 맡은 드랍오프 자리.
WORKCELLS = [
    ('omx_01', 'omx_01', ['픽업1'], []),
    ('omx_02', 'omx_02', ['픽업2'], []),
    ('omx_03', 'omx_03', ['픽업3'], []),
]

# 팔이 한 번 움직이는 데 걸리는 시간 [s].
#
# RMF 는 이 시간을 모른다. 우리가 끝났다고 알릴 때까지 기다릴 뿐이다.
ACTION_SECONDS = 4.0

# 물품 종류별 가상 모방학습 policy. 모든 OMX가 같은 다섯 policy를 제공한다.
# 각 값은 시간 비율과 joint1~4 자세이며 실제 추론기 연결 전 동작 검증용이다.
JOINT_NAMES = ['joint1', 'joint2', 'joint3', 'joint4']
HOME_POSE = [0.0, -1.0, 0.3, 0.7]
POLICY_MOTIONS = {
    'policy_1': [[0.00, 0.45, -0.30, 0.65], [0.00, 0.75, -0.55, 0.90]],
    'policy_2': [[0.35, 0.35, -0.20, 0.55], [0.55, 0.70, -0.45, 0.80]],
    'policy_3': [[-0.35, 0.35, -0.20, 0.55], [-0.55, 0.70, -0.45, 0.80]],
    'policy_4': [[0.20, 0.15, 0.05, 0.45], [0.35, 0.55, -0.20, 0.70]],
    'policy_5': [[-0.20, 0.15, 0.05, 0.45], [-0.35, 0.55, -0.20, 0.70]],
}


def now_msg(node):
    stamp = node.get_clock().now().to_msg()
    return Time(sec=stamp.sec, nanosec=stamp.nanosec)


class Workcell:
    """설비 한 대. 맡은 자리 이름으로 불린다."""

    def __init__(self, node, robot_id, namespace, dispensers, ingestors):
        self.node = node
        self.robot_id = robot_id
        self.namespace = namespace
        self.dispensers = dispensers
        self.ingestors = ingestors
        self.busy = False
        self.active_request = None
        self.completed_requests = set()
        self.lock = threading.Lock()
        self.arm = node.create_publisher(
            JointTrajectory, f'/{namespace}/arm_controller/joint_trajectory', 10)

    def serves(self, guid):
        return guid in self.dispensers or guid in self.ingestors

    def run_policy(self, policy_id, seconds):
        """선택한 가상 policy의 관절 궤적 전체를 한 번에 보낸다."""
        message = JointTrajectory()
        message.joint_names = list(JOINT_NAMES)
        poses = [*POLICY_MOTIONS[policy_id], HOME_POSE]
        for index, pose in enumerate(poses, start=1):
            point = JointTrajectoryPoint()
            point.positions = list(pose)
            at = seconds * index / len(poses)
            point.time_from_start.sec = int(at)
            point.time_from_start.nanosec = int((at % 1) * 1e9)
            message.points.append(point)
        self.arm.publish(message)


class WorkcellAdapter(rclpy.node.Node):

    def __init__(self):
        super().__init__('project1_workcell')

        # RMF 는 상태를 **transient local** 로 듣는다. 늦게 뜬 쪽도 마지막
        # 상태를 받아야 워크셀이 있다는 것을 알기 때문이다.
        state_qos = QoSProfile(
            depth=10,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.dispenser_states = self.create_publisher(
            DispenserState, '/dispenser_states', state_qos)
        self.ingestor_states = self.create_publisher(
            IngestorState, '/ingestor_states', state_qos)
        self.dispenser_results = self.create_publisher(
            DispenserResult, '/dispenser_results', 10)
        self.ingestor_results = self.create_publisher(
            IngestorResult, '/ingestor_results', 10)

        self.cells = [
            Workcell(self, robot_id, namespace, dispensers, ingestors)
            for robot_id, namespace, dispensers, ingestors in WORKCELLS
        ]

        # Fleet adapter의 요청은 transient local이다. 워크셀이 늦게 떠도 이미
        # 보낸 픽업 요청을 받아야 하므로 같은 QoS로 구독한다.
        self.create_subscription(
            DispenserRequest, '/dispenser_requests',
            lambda msg: self.on_request(msg, dispenser=True), state_qos)
        self.create_subscription(
            IngestorRequest, '/ingestor_requests',
            lambda msg: self.on_request(msg, dispenser=False), state_qos)

        # 상태를 안 내면 RMF 가 이 워크셀을 없는 것으로 보고 요청조차 안 한다.
        self.create_timer(1.0, self.publish_states)

        served = sum(len(c.dispensers) + len(c.ingestors) for c in self.cells)
        self.get_logger().info(
            f'워크셀 {len(self.cells)}대, 맡은 자리 {served}곳을 RMF 에 이었습니다.')

    def publish_states(self):
        for cell in self.cells:
            mode = DispenserState.BUSY if cell.busy else DispenserState.IDLE
            for guid in cell.dispensers:
                self.dispenser_states.publish(DispenserState(
                    time=now_msg(self), guid=guid, mode=mode,
                    request_guid_queue=[], seconds_remaining=0.0))
            for guid in cell.ingestors:
                self.ingestor_states.publish(IngestorState(
                    time=now_msg(self), guid=guid, mode=mode,
                    request_guid_queue=[], seconds_remaining=0.0))

    # `handle` 이라고 부르면 안 된다. rclpy 의 Node 가 같은 이름의 속성을
    # 쓰는데, 메서드로 덮으면 Node.__init__ 이 `with self.handle:` 에서
    # TypeError 로 죽는다 — 노드가 아예 안 뜬다.
    def on_request(self, msg, dispenser):
        cell = next((c for c in self.cells if c.serves(msg.target_guid)), None)
        if cell is None:
            # 우리 것이 아니다. 남의 워크셀 요청일 수 있으므로 조용히 넘긴다.
            return

        # 같은 요청은 답을 받을 때까지 반복된다. 같은 GUID로 팔을 두 번
        # 움직이지 않고, 현재 상태만 다시 답한다.
        with cell.lock:
            if msg.request_guid in cell.completed_requests:
                repeated_status = DispenserResult.SUCCESS
            elif cell.active_request == msg.request_guid:
                repeated_status = DispenserResult.ACKNOWLEDGED
            else:
                repeated_status = None
            if repeated_status is not None:
                pass
            elif cell.busy:
                return
            else:
                cell.busy = True
                cell.active_request = msg.request_guid
        if repeated_status is not None:
            self.answer(msg, dispenser, repeated_status)
            return

        self.get_logger().info(
            f'[{cell.robot_id}] {msg.target_guid} 요청 받음 '
            f'({msg.request_guid})')
        self.answer(msg, dispenser, DispenserResult.ACKNOWLEDGED)

        policy_id = msg.items[0].type_guid if msg.items else 'policy_1'
        if policy_id not in POLICY_MOTIONS:
            self.get_logger().error(
                f'[{cell.robot_id}] 알 수 없는 물품 policy [{policy_id}]')
            with cell.lock:
                cell.busy = False
                cell.active_request = None
            self.answer(msg, dispenser, DispenserResult.FAILED)
            return
        self.get_logger().info(
            f'[{cell.robot_id}] 물품 [{policy_id}] 가상 policy 실행')
        cell.run_policy(policy_id, ACTION_SECONDS)

        def finish():
            timer.cancel()
            with cell.lock:
                cell.busy = False
                cell.active_request = None
                cell.completed_requests.add(msg.request_guid)
            self.get_logger().info(f'[{cell.robot_id}] {msg.target_guid} 끝.')
            self.answer(msg, dispenser, DispenserResult.SUCCESS)

        timer = self.create_timer(ACTION_SECONDS, finish)

    def answer(self, msg, dispenser, status):
        if dispenser:
            self.dispenser_results.publish(DispenserResult(
                time=now_msg(self), request_guid=msg.request_guid,
                source_guid=msg.target_guid, status=status))
        else:
            self.ingestor_results.publish(IngestorResult(
                time=now_msg(self), request_guid=msg.request_guid,
                source_guid=msg.target_guid, status=status))


def main(argv=sys.argv):
    rclpy.init(args=argv)
    node = WorkcellAdapter()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()


if __name__ == '__main__':
    main()
