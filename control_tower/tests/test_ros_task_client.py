"""Open-RMF ApiRequest/ApiResponse와 TaskSummary ROS adapter 테스트."""

import json

import pytest
from rclpy.qos import DurabilityPolicy, ReliabilityPolicy
from rmf_task_msgs.msg import ApiRequest, ApiResponse, TaskSummary

from control_tower.rmf_adapter.ros_task_client import (
    RosTaskApiClient,
    RosTaskSummaryObserver,
)
from control_tower.rmf_adapter.task_outbox import InMemoryRmfOutboxRepository


class RecordingPublisher:
    def __init__(self):
        self.last_message = None

    def publish(self, message):
        self.last_message = message


class RecordingNode:
    def __init__(self):
        self.publisher = RecordingPublisher()
        self.response_callback = None
        self.publisher_qos = None

    def create_publisher(self, message_type, topic, qos):
        assert message_type is ApiRequest
        assert topic == "task_api_requests"
        self.publisher_qos = qos
        return self.publisher

    def create_subscription(self, message_type, topic, callback, qos):
        assert message_type is ApiResponse
        assert topic == "task_api_responses"
        self.response_callback = callback
        return object()


def _success_json(task_id: str = "rmf-task-1") -> str:
    return json.dumps(
        {
            "success": True,
            "state": {"booking": {"id": task_id}, "status": "queued"},
        }
    )


def test_ros_client_publishes_request_and_correlates_final_response() -> None:
    """다른 request의 응답 또는 ACK가 제출 결과로 오인되는 회귀를 막는다."""
    node = RecordingNode()

    def finish(_node, future, timeout_sec):
        acknowledge = ApiResponse()
        acknowledge.type = ApiResponse.TYPE_ACKNOWLEDGE
        acknowledge.request_id = "req-1"
        acknowledge.json_msg = "{}"
        node.response_callback(acknowledge)
        assert future.done() is False

        other = ApiResponse()
        other.type = ApiResponse.TYPE_RESPONDING
        other.request_id = "other-request"
        other.json_msg = _success_json("wrong-task")
        node.response_callback(other)
        assert future.done() is False

        response = ApiResponse()
        response.type = ApiResponse.TYPE_RESPONDING
        response.request_id = "req-1"
        response.json_msg = _success_json()
        node.response_callback(response)

    client = RosTaskApiClient(node, spin_until_future_complete=finish)
    payload = {"type": "dispatch_task_request", "request": {}}

    accepted = client.submit("req-1", payload, timeout_s=2.0)

    sent = node.publisher.last_message
    assert sent.request_id == "req-1"
    assert json.loads(sent.json_msg) == payload
    assert accepted.accepted is True
    assert accepted.rmf_task_id == "rmf-task-1"
    assert node.publisher_qos.depth == 1
    assert node.publisher_qos.reliability is ReliabilityPolicy.RELIABLE
    assert node.publisher_qos.durability is DurabilityPolicy.TRANSIENT_LOCAL


def test_ros_client_timeout_does_not_invent_a_response() -> None:
    """응답 없는 제출이 성공 처리되는 회귀를 막는다."""
    node = RecordingNode()
    client = RosTaskApiClient(
        node,
        spin_until_future_complete=lambda node, future, timeout_sec: None,
    )

    with pytest.raises(TimeoutError, match="timed out"):
        client.submit("req-1", {"type": "dispatch_task_request"}, 0.1)


def _summary(task_id: str, state: int, robot: str = "PK-01") -> TaskSummary:
    message = TaskSummary()
    message.fleet_name = "pinky_fleet"
    message.task_id = task_id
    message.state = state
    message.robot_name = robot
    return message


def test_summary_observer_ignores_unknown_task() -> None:
    """외부에서 생성된 RMF task가 Control Tower 업무를 임의 변경하지 못하게 한다."""
    repository = InMemoryRmfOutboxRepository()
    observer = RosTaskSummaryObserver(repository)

    assert observer.on_summary(
        _summary("unknown", TaskSummary.STATE_ACTIVE), observed_at_ms=1_000
    ) is False


def test_summary_observer_applies_only_newer_known_task_state() -> None:
    """주기적으로 오는 오래된 summary가 완료 상태를 되돌리는 회귀를 막는다."""
    repository = InMemoryRmfOutboxRepository()
    repository.task_ids_by_step[42] = "rmf-task-1"
    observer = RosTaskSummaryObserver(repository)

    active = observer.on_summary(
        _summary("rmf-task-1", TaskSummary.STATE_ACTIVE),
        observed_at_ms=2_000,
    )
    stale = observer.on_summary(
        _summary("rmf-task-1", TaskSummary.STATE_QUEUED),
        observed_at_ms=1_000,
    )

    assert active is True
    assert stale is False
    assert repository.task_updates["rmf-task-1"].step_state == "running"


def test_summary_observer_ignores_an_unsupported_state() -> None:
    """새 RMF 상태값 하나가 ROS subscription callback을 중단시키는 회귀를 막는다."""
    repository = InMemoryRmfOutboxRepository()
    repository.task_ids_by_step[42] = "rmf-task-1"
    observer = RosTaskSummaryObserver(repository)

    assert observer.on_summary(
        _summary("rmf-task-1", 99), observed_at_ms=2_000
    ) is False
    assert repository.task_updates == {}
