#!/usr/bin/env python3
"""project1-ver2 프로젝트의 RMF 워크셀 어댑터.

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

# 로봇 ID, ROS 네임스페이스, 모델, 맡은 자리와 배포된 policy.
WORKCELLS = [
    ('omx_03', 'omx_03', 'omx_f', ['픽업1'], [], ['Sandwitch@1.0.0']),
    ('omx_04', 'omx_04', 'omx_f', ['픽업3'], [], ['Sandwitch@1.0.0']),
]

# 팔이 한 번 움직이는 데 걸리는 시간 [s].
#
# RMF 는 이 시간을 모른다. 우리가 끝났다고 알릴 때까지 기다릴 뿐이다.
ACTION_SECONDS = 4.0

# 팔 궤적의 마지막 시각과 동시에 RMF에 성공을 알리면 관절 컨트롤러가
# 마지막 자세를 정착시키는 동안 모바일 로봇이 출발할 수 있다. 궤적이 끝난
# 뒤 이 시간만큼 더 기다린 다음 성공을 알려 핑키가 안전하게 출발하게 한다.
ARM_SETTLE_SECONDS = 3.0

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

# 학습 policy 실행기를 연결하기 전 controller·RMF 경로를 검증하는 저속 궤적.
# 실제 ACT 추론 결과가 아니며 배포된 policy ID에만 사용한다.
MODEL_TEST_MOTIONS = {
    'open_manipulator_x': {
        'joints': ['joint1', 'joint2', 'joint3', 'joint4'],
        'home': [0.0, -1.0, 0.3, 0.7],
        'poses': [[0.15, -0.85, 0.25, 0.65], [-0.15, -0.85, 0.25, 0.65]],
    },
    'omx_f': {
        'joints': ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1'],
        'home': [0.0, -1.0, 0.3, 0.7, 0.0, 0.0],
        'poses': [[0.15, -0.85, 0.25, 0.65, 0.10, 0.0],
                  [-0.15, -0.85, 0.25, 0.65, -0.10, 0.0]],
    },
}

# 2usang/trihouse-sandwich episode 0의 성공 시연을 1초 간격으로 추린 값.
# [시각(s), joint1~5(deg), gripper(deg)]이며 controller 전송 때 rad로 바꾼다.
SANDWICH_REPLAY_DEG = [
    [0.0, -0.611, -66.398, 55.018, 47.692, 0.415, 60.147],
    [1.0, -0.611, -66.398, 55.018, 47.692, 0.415, 60.147],
    [2.0, -0.611, -66.398, 55.018, 47.692, 0.415, 60.147],
    [3.0, -0.611, -66.398, 55.018, 47.692, 0.415, 60.147],
    [4.0, -0.611, -66.398, 55.018, 47.692, 0.415, 60.147],
    [5.0, -0.659, -66.398, 55.018, 47.692, 0.415, 60.147],
    [6.0, -0.708, -66.545, 55.018, 43.834, 0.562, 61.001],
    [7.0, -3.053, -66.545, 54.969, 28.547, 0.317, 60.977],
    [8.0, -8.474, -66.545, 54.872, 24.884, 0.708, 59.487],
    [9.0, -18.437, -66.252, 37.729, 25.421, 0.073, 59.219],
    [10.0, -30.696, -49.109, 20.147, 25.079, -7.937, 58.999],
    [11.0, -33.529, -40.757, 10.916, 21.270, -7.253, 58.632],
    [12.0, -33.480, -39.585, 10.183, 17.216, -3.639, 58.657],
    [13.0, -33.431, -34.945, 6.325, 16.044, -3.248, 58.657],
    [14.0, -33.480, -34.212, 6.374, 15.263, -3.492, 58.657],
    [15.0, -33.431, -32.405, 6.716, 14.481, -3.541, 58.681],
    [16.0, -33.431, -32.259, 6.618, 14.432, -3.492, 58.681],
    [17.0, -34.896, -26.593, 6.716, 12.088, -3.394, 58.657],
    [18.0, -34.408, -21.661, -0.659, 12.381, -0.073, 58.388],
    [19.0, -34.164, -17.216, -3.980, 12.234, -0.122, 57.875],
    [20.0, -33.187, -14.286, -5.934, 12.186, -0.073, 57.680],
    [21.0, -32.112, -13.211, -6.032, 11.990, -0.366, 53.187],
    [22.0, -31.233, -14.530, -5.836, 9.499, -0.171, 47.131],
    [23.0, -33.529, -20.684, -5.055, 10.183, -0.122, 46.716],
    [24.0, -45.250, -24.298, -1.245, 13.260, 1.783, 46.716],
    [25.0, -51.013, -24.835, 6.862, 12.772, 1.685, 46.740],
    [26.0, -60.488, -20.488, 7.692, 14.969, 3.932, 46.716],
    [27.0, -65.763, -12.381, 7.839, 20.391, 7.497, 46.716],
    [28.0, -69.035, -3.883, 7.448, 19.365, 7.448, 46.862],
    [29.0, -68.742, -2.711, 6.569, 18.486, 7.497, 59.243],
    [30.0, -65.226, -21.465, 10.574, 18.193, 7.399, 59.341],
    [31.0, -48.767, -56.337, 45.250, 7.106, 7.253, 59.316],
    [32.0, -9.304, -66.447, 55.263, 12.088, 7.448, 59.365],
    [33.0, 1.490, -66.398, 55.263, 42.076, 7.399, 59.365],
    [34.0, 1.050, -66.447, 55.263, 48.620, 7.399, 59.365],
    [34.7, 1.050, -66.447, 55.263, 48.620, 7.350, 59.365],
]


def now_msg(node):
    stamp = node.get_clock().now().to_msg()
    return Time(sec=stamp.sec, nanosec=stamp.nanosec)


class Workcell:
    """설비 한 대. 맡은 자리 이름으로 불린다."""

    def __init__(self, node, robot_id, namespace, model, dispensers, ingestors,
                 deployed_policies):
        self.node = node
        self.robot_id = robot_id
        self.namespace = namespace
        self.model = model
        self.dispensers = dispensers
        self.ingestors = ingestors
        self.deployed_policies = set(deployed_policies)
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

    def run_deployed_policy_test(self, policy_id, seconds):
        """배포 policy의 추론기 연결 전, 모델별 안전 시험 궤적을 보낸다."""
        profile = MODEL_TEST_MOTIONS[self.model]
        message = JointTrajectory()
        message.joint_names = list(profile['joints'])
        poses = [*profile['poses'], profile['home']]
        for index, pose in enumerate(poses, start=1):
            point = JointTrajectoryPoint()
            point.positions = list(pose)
            at = seconds * index / len(poses)
            point.time_from_start.sec = int(at)
            point.time_from_start.nanosec = int((at % 1) * 1e9)
            message.points.append(point)
        self.node.get_logger().warning(
            f'[{self.robot_id}] [{policy_id}] ACT 추론 전 controller 시험 동작')
        self.arm.publish(message)

    def run_sandwich_replay(self, policy_id):
        """학습 episode의 샌드위치 집기 시연을 Gazebo에서 관절 재생한다."""
        message = JointTrajectory()
        message.joint_names = list(MODEL_TEST_MOTIONS['omx_f']['joints'])
        lead_in = 1.0
        for row in SANDWICH_REPLAY_DEG:
            point = JointTrajectoryPoint()
            point.positions = [math.radians(value) for value in row[1:]]
            at = lead_in + row[0]
            point.time_from_start.sec = int(at)
            point.time_from_start.nanosec = int((at % 1) * 1e9)
            message.points.append(point)
        self.node.get_logger().info(
            f'[{self.robot_id}] [{policy_id}] 학습 episode 0 샌드위치 동작 재생')
        self.arm.publish(message)
        return lead_in + SANDWICH_REPLAY_DEG[-1][0]


class WorkcellAdapter(rclpy.node.Node):

    def __init__(self):
        super().__init__('project1_ver2_workcell')

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
            Workcell(self, robot_id, namespace, model, dispensers, ingestors, policies)
            for robot_id, namespace, model, dispensers, ingestors, policies in WORKCELLS
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
        is_deployed = policy_id in cell.deployed_policies
        if (policy_id != 'armLoad' and policy_id not in POLICY_MOTIONS
                and not is_deployed):
            self.get_logger().error(
                f'[{cell.robot_id}] 알 수 없는 물품 policy [{policy_id}]')
            with cell.lock:
                cell.busy = False
                cell.active_request = None
            self.answer(msg, dispenser, DispenserResult.FAILED)
            return
        execution_seconds = ACTION_SECONDS
        replay_name = policy_id.split('@', 1)[0].lower()
        if (is_deployed and cell.model == 'omx_f'
                and replay_name in ('sandwich', 'sandwitch')):
            execution_seconds = cell.run_sandwich_replay(policy_id)
        elif is_deployed:
            cell.run_deployed_policy_test(policy_id, ACTION_SECONDS)
        elif policy_id == 'armLoad':
            # Mock 또는 별도 policy가 없는 실설비의 기본 적재 동작. RMF 요청은
            # 정상 완료하되 존재하지 않는 관절 policy를 억지로 실행하지 않는다.
            self.get_logger().info(
                f'[{cell.robot_id}] 기본 armLoad 실행 (등록 policy 없음)')
        else:
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

        timer = self.create_timer(execution_seconds + ARM_SETTLE_SECONDS, finish)

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
