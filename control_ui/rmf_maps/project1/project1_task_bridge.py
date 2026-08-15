#!/usr/bin/env python3
"""project1 프로젝트의 작업 다리 — 앱이 만든 작업을 RMF 에 넣는다.

rmf_control_ui 가 맵 프로젝트에서 생성했다. 손으로 고치면 다음 저장 때
덮어써진다.

  project1_task_bridge.py --submit 작업.json

작업.json 은 `robot_task_request` 나 `dispatch_task_request` 한 덩어리다.
성공하면 RMF 의 답을 그대로 찍고 0 으로 끝난다.
"""

import argparse
import json
import sys
import uuid

import rclpy
import rclpy.node
from rclpy.qos import QoSProfile, QoSDurabilityPolicy, QoSHistoryPolicy

from rmf_task_msgs.msg import ApiRequest, ApiResponse

FLEET_NAME = 'project1_pinky'

# RMF 의 task API 는 transient_local 이다. 늦게 붙는 쪽도 마지막 것을 받는다.
API_QOS = QoSProfile(
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=10,
    durability=QoSDurabilityPolicy.TRANSIENT_LOCAL)


def main(argv=sys.argv):
    parser = argparse.ArgumentParser(prog='project1' + '_task_bridge')
    parser.add_argument('--submit', required=True,
                        help='보낼 작업 JSON 파일')
    parser.add_argument('--timeout', type=float, default=15.0,
                        help='답을 기다리는 초')
    args = parser.parse_args(argv[1:])

    with open(args.submit, encoding='utf-8') as handle:
        payload = json.load(handle)

    rclpy.init(args=None)
    node = rclpy.node.Node('project1_pinky' + '_task_bridge')
    publisher = node.create_publisher(ApiRequest, 'task_api_requests', API_QOS)

    request = ApiRequest()
    request.request_id = 'rmf_control_ui-' + str(uuid.uuid4())[:8]
    request.json_msg = json.dumps(payload, ensure_ascii=False)

    answer = {}

    def on_response(message):
        # 남의 요청에 대한 답도 같은 토픽으로 온다.
        if message.request_id != request.request_id:
            return
        answer['body'] = json.loads(message.json_msg)

    node.create_subscription(ApiResponse, 'task_api_responses',
                             on_response, API_QOS)

    # 구독이 붙기 전에 실으면 답을 놓친다. 한 바퀴 돌려 놓고 보낸다.
    rclpy.spin_once(node, timeout_sec=0.5)
    publisher.publish(request)

    deadline = node.get_clock().now().nanoseconds + int(args.timeout * 1e9)
    while 'body' not in answer:
        if node.get_clock().now().nanoseconds > deadline:
            print(json.dumps({
                'success': False,
                'errors': [{'code': 0, 'category': 'timeout', 'detail':
                            'RMF 가 답하지 않았습니다. fleet adapter 가 떠 '
                            '있는지 확인하세요.'}],
            }, ensure_ascii=False))
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
            return 1
        rclpy.spin_once(node, timeout_sec=0.2)

    print(json.dumps(answer['body'], ensure_ascii=False))
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
    return 0 if answer['body'].get('success') else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
