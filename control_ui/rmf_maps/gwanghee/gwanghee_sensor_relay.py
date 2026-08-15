#!/usr/bin/env python3
"""gwanghee 프로젝트의 센서 relay.

rmf_control_ui 가 맵 프로젝트에서 생성했다. 손으로 고치면 다음 저장 때
덮어써진다.

로봇의 라이다와 카메라를 구독해서 앱이 읽을 수 있는 파일로 내려 준다. 앱에는
rclpy 가 없고, 카메라 영상은 `ros2 topic echo` 로 읽기에 너무 크다.

파일은 --out 디렉터리에 로봇 ID 로 쌓인다.

    <ID>.scan   라이다 한 줄 (텍스트)
    <ID>.frame  카메라 한 장 (RGBA 날바이트, 앞에 작은 머리글)

둘 다 임시 파일에 쓰고 rename 한다. 앱이 반쯤 쓰인 파일을 읽는 일이 없다.
"""

import argparse
import os
import struct
import sys

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

from sensor_msgs.msg import Image, LaserScan

# (RMF 가 아는 이름, ROS 네임스페이스)
ROBOTS = [
    ('PK_03', 'pinky_03'),
]

# 카메라를 줄여서 보낼 크기. 원본 그대로 두면 한 장에 2.7MB 라 디스크만 먹는다.
# 로봇 상세에서 보기에는 이 정도면 넉넉하다.
FRAME_WIDTH = 320
FRAME_HEIGHT = 180

# 라이다는 이만큼으로 솎는다. 640개를 다 그려도 눈에 보이는 차이가 없다.
SCAN_POINTS = 180

# 카메라를 초당 몇 장까지 내릴까. 앱은 0.2초마다 읽으므로 이보다 많이 내려도
# 보이지 않고 디스크만 먹는다.
FRAME_INTERVAL = 1.0 / 6

# 카메라 파일 머리글. 앱이 이 네 글자로 파일이 맞는지 본다.
FRAME_MAGIC = b'RSIM'


def write_atomic(path, data, binary=True):
    """반쯤 쓰인 파일을 앱이 읽지 않도록 임시 파일에 쓰고 옮긴다."""
    tmp = path + '.tmp'
    with open(tmp, 'wb' if binary else 'w') as handle:
        handle.write(data)
    os.replace(tmp, path)


class SensorRelay(Node):

    def __init__(self, out_dir):
        super().__init__('gwanghee_sensor_relay')
        self.out_dir = out_dir
        self.last_frame = {}
        os.makedirs(out_dir, exist_ok=True)
        for robot_id, namespace in ROBOTS:
            self.create_subscription(
                LaserScan, f'/{namespace}/scan',
                lambda msg, rid=robot_id: self.on_scan(rid, msg),
                qos_profile_sensor_data)
            self.create_subscription(
                Image, f'/{namespace}/camera/image_raw',
                lambda msg, rid=robot_id: self.on_image(rid, msg),
                qos_profile_sensor_data)
            self.get_logger().info(f'[{robot_id}] /{namespace} 를 봅니다.')

    def on_scan(self, robot_id, msg):
        ranges = list(msg.ranges)
        if not ranges:
            return
        # 고르게 솎는다. 앞쪽만 잘라내면 뒤가 안 보인다.
        step = max(1, len(ranges) // SCAN_POINTS)
        thinned = ranges[::step]
        # 무한대와 NaN 은 텍스트로 옮기면 파서가 걸린다. 잴 수 없었다는 뜻이므로
        # 최대 거리로 적는다.
        cleaned = []
        for value in thinned:
            if value != value or value == float('inf') or value > msg.range_max:
                cleaned.append(msg.range_max)
            else:
                cleaned.append(value)
        head = '{:.6f},{:.6f},{:.3f},{:.3f}'.format(
            msg.angle_min, msg.angle_max, msg.range_min, msg.range_max)
        body = ','.join('{:.3f}'.format(value) for value in cleaned)
        write_atomic(
            os.path.join(self.out_dir, robot_id + '.scan'),
            head + '\n' + body + '\n', binary=False)

    def on_image(self, robot_id, msg):
        # 속도를 제한한다. 앱은 0.2초마다 읽으므로 더 자주 내려도 보이지 않는다.
        now = self.get_clock().now().nanoseconds / 1e9
        if now - self.last_frame.get(robot_id, 0.0) < FRAME_INTERVAL:
            return
        self.last_frame[robot_id] = now

        pixels = self.to_rgba(msg)
        if pixels is None:
            return
        header = FRAME_MAGIC + struct.pack('<II', FRAME_WIDTH, FRAME_HEIGHT)
        write_atomic(
            os.path.join(self.out_dir, robot_id + '.frame'), header + pixels)

    def to_rgba(self, msg):
        """영상을 줄여서 RGBA 로 만든다.

        화소를 파이썬 반복문으로 옮기면 안 된다. 320x180 한 장에 5만 7천 번이고,
        두 대가 초당 열두 장이면 코어 하나를 통째로 먹는다 — 실제로 101% 를
        썼다. numpy 는 rclpy 가 이미 쓰고 있으므로 새로 받을 것이 없다.
        """
        if msg.encoding not in ('rgb8', 'bgr8'):
            self.get_logger().warn(
                f'모르는 영상 형식 [{msg.encoding}] 입니다.', once=True)
            return None

        frame = np.frombuffer(msg.data, dtype=np.uint8)
        # step 은 한 줄의 바이트 수다. 폭보다 클 수 있어서 잘라 낸다.
        frame = frame.reshape(msg.height, msg.step)[:, :msg.width * 3]
        frame = frame.reshape(msg.height, msg.width, 3)

        # 가장 가까운 화소를 집는다. 보간은 필요 없다 — 보여 주기용이다.
        rows = (np.arange(FRAME_HEIGHT) * msg.height) // FRAME_HEIGHT
        columns = (np.arange(FRAME_WIDTH) * msg.width) // FRAME_WIDTH
        small = frame[rows][:, columns]
        if msg.encoding == 'bgr8':
            small = small[:, :, ::-1]

        alpha = np.full((FRAME_HEIGHT, FRAME_WIDTH, 1), 255, dtype=np.uint8)
        return np.concatenate([small, alpha], axis=2).tobytes()


def main(argv=sys.argv):
    parser = argparse.ArgumentParser(prog='gwanghee_sensor_relay')
    parser.add_argument('-o', '--out', required=True)
    args = parser.parse_args(rclpy.utilities.remove_ros_args(argv)[1:])

    rclpy.init(args=argv)
    node = SensorRelay(args.out)
    if not ROBOTS:
        node.get_logger().warn('볼 로봇이 없습니다.')
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    # rclpy 의 신호 처리기가 먼저 context 를 닫아 놓는 일이 있다. 그때 또
    # 부르면 예외가 올라와, 멀쩡히 끝난 것이 죽은 것처럼 보인다.
    if rclpy.ok():
        rclpy.shutdown()


if __name__ == '__main__':
    main(sys.argv)
