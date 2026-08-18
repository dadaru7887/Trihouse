"""Open-RMF task API ROS topic을 Control Tower 동기 port로 변환한다."""

import json
from threading import Lock
from typing import Any, Callable

import rclpy
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from rclpy.task import Future
from rmf_fleet_msgs.msg import FleetState
from rmf_task_msgs.msg import ApiRequest, ApiResponse, TaskSummary

from .task_api import (
    DispatchAcceptance,
    normalize_task_summary,
    parse_dispatch_response,
    normalize_fleet_state,
)
from .task_outbox import RmfOutboxRepository


class RosTaskApiClient:
    """request ID로 ApiResponse를 상관시키는 동기 task submit transport."""

    def __init__(
        self,
        node: Any,
        *,
        request_topic: str = "task_api_requests",
        response_topic: str = "task_api_responses",
        spin_until_future_complete: Callable[..., None] = (
            rclpy.spin_until_future_complete
        ),
    ) -> None:
        self._node = node
        self._spin_until_future_complete = spin_until_future_complete
        self._lock = Lock()
        self._pending: dict[str, Future] = {}
        request_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._publisher = node.create_publisher(
            ApiRequest, request_topic, request_qos
        )
        self._subscription = node.create_subscription(
            ApiResponse, response_topic, self._on_response, 10
        )

    def submit(
        self,
        request_id: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> DispatchAcceptance:
        if not request_id.strip():
            raise ValueError("request_id is required")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        future = Future()
        with self._lock:
            if request_id in self._pending:
                raise ValueError(f"request is already pending: {request_id}")
            self._pending[request_id] = future

        message = ApiRequest()
        message.request_id = request_id
        message.json_msg = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        )
        try:
            self._publisher.publish(message)
            self._spin_until_future_complete(
                self._node, future, timeout_sec=timeout_s
            )
            if not future.done():
                future.cancel()
                raise TimeoutError("RMF task API timed out")
            response = future.result()
            if not isinstance(response, dict):
                raise RuntimeError("RMF task API returned an invalid response")
            return parse_dispatch_response(response)
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def _on_response(self, message: ApiResponse) -> None:
        if message.type != ApiResponse.TYPE_RESPONDING:
            return
        with self._lock:
            future = self._pending.get(message.request_id)
        if future is None or future.done():
            return
        try:
            response = json.loads(message.json_msg)
        except (TypeError, json.JSONDecodeError) as error:
            future.set_exception(
                RuntimeError(f"RMF task API returned invalid JSON: {error}")
            )
            return
        future.set_result(response)


class RosTaskSummaryObserver:
    """알려진 RMF TaskSummary만 Control Tower read model에 적용한다."""

    def __init__(self, repository: RmfOutboxRepository) -> None:
        self._repository = repository
        self._subscription: Any | None = None

    def attach(self, node: Any, topic: str = "task_summaries") -> Any:
        def receive(message: TaskSummary) -> None:
            observed_at_ms = node.get_clock().now().nanoseconds // 1_000_000
            self.on_summary(message, observed_at_ms=observed_at_ms)

        self._subscription = node.create_subscription(
            TaskSummary, topic, receive, 10
        )
        return self._subscription

    def on_summary(
        self, message: TaskSummary, *, observed_at_ms: int
    ) -> bool:
        try:
            update = normalize_task_summary(
                message, observed_at_ms=observed_at_ms
            )
        except (TypeError, ValueError):
            return False
        if not self._repository.knows_task(update.task_id):
            return False
        return self._repository.apply_task_update(update)


class RosFleetStateObserver:
    """`fleet_states` 로 돌아오는 낙찰 사실만 원장에 반영한다.

    `RosTaskSummaryObserver` 와 형제이나 보는 토픽이 다르다. 이 RMF 배포는
    `task_summaries` 에 아무것도 발행하지 않으므로(2026-08-19 실측: 12초에 0건,
    같은 시간 `fleet_states` 97건) 그쪽만으로는 배정이 영원히 돌아오지 않는다.
    그러면 dispatch 가 `RMF_ASSIGNMENT_PENDING` 으로 재시도를 소진해 `dead_letter`
    가 되고, RMF 와 로봇은 정상인데 원장만 실패로 남는다.

    우리가 낸 작업만 반영한다. RMF 는 다른 경로로 들어온 작업도 같은 fleet 에
    나르므로, 모르는 `task_id` 를 원장에 쓰면 남의 작업을 우리 것으로 만든다.
    """

    def __init__(self, repository: RmfOutboxRepository) -> None:
        self._repository = repository
        self._subscription: Any | None = None

    def attach(self, node: Any, topic: str = "fleet_states") -> Any:
        def receive(message: FleetState) -> None:
            observed_at_ms = node.get_clock().now().nanoseconds // 1_000_000
            self.on_fleet_state(message, observed_at_ms=observed_at_ms)

        self._subscription = node.create_subscription(
            FleetState, topic, receive, 10
        )
        return self._subscription

    def on_fleet_state(self, message: FleetState, *, observed_at_ms: int) -> int:
        """반영한 건수를 돌려준다."""
        try:
            updates = normalize_fleet_state(message, observed_at_ms=observed_at_ms)
        except (TypeError, ValueError):
            return 0
        applied = 0
        for update in updates:
            if not self._repository.knows_task(update.task_id):
                continue
            if self._repository.apply_task_update(update):
                applied += 1
        return applied
