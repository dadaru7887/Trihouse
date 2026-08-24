#!/usr/bin/env python3
"""RMF dispatcher 에 남아 있는 task 를 ROS api request 로 취소한다.

FMS 에서 job 을 취소해도 RMF 는 그 사실을 모른다. 남은 task 는 fleet adapter 에
계속 재배정되고, adapter 는 이미 `cancelled` 인 job_step 을 claim 하려다
HTTP 409 를 받는다. 그 실패가 replan 을 부르고 replan 이 다시 claim 을 불러
초당 수백 번 도는 굶주림 고리가 된다. 새 주문은 그 고리에 밀려 영원히 배정되지
않는다.
"""

import json
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
from rmf_task_msgs.msg import ApiRequest, ApiResponse


class Canceller(Node):
    def __init__(self, task_ids: list[str]) -> None:
        super().__init__("trihouse_rmf_cancel_task")
        qos = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self._pub = self.create_publisher(ApiRequest, "/task_api_requests", qos)
        self.create_subscription(ApiResponse, "/task_api_responses", self._on_response, qos)
        self._task_ids = task_ids
        self._seen: dict[str, str] = {}

    def send(self) -> None:
        for index, task_id in enumerate(self._task_ids):
            message = ApiRequest()
            message.request_id = f"trihouse-cancel-{index}-{task_id}"
            message.json_msg = json.dumps(
                {"type": "cancel_task_request", "task_id": task_id}
            )
            self._pub.publish(message)
            self.get_logger().info(f"cancel 요청 발행: {task_id}")

    def _on_response(self, message: ApiResponse) -> None:
        if not message.request_id.startswith("trihouse-cancel-"):
            return
        self._seen[message.request_id] = message.json_msg
        self.get_logger().info(f"응답 {message.request_id}: {message.json_msg}")


def main() -> int:
    task_ids = sys.argv[1:]
    if not task_ids:
        print("사용법: rmf_cancel_task.py <task_id> [<task_id> ...]", file=sys.stderr)
        return 2

    rclpy.init()
    node = Canceller(task_ids)
    # 발행자가 dispatcher 와 연결될 시간을 준다. 바로 publish 하면 아무도 못 받는다.
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline and node._pub.get_subscription_count() == 0:
        rclpy.spin_once(node, timeout_sec=0.2)
    node.get_logger().info(f"구독자 수 = {node._pub.get_subscription_count()}")
    node.send()

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and len(node._seen) < len(task_ids):
        rclpy.spin_once(node, timeout_sec=0.2)

    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
