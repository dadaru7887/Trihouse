"""EstimateTaskEnergy ROS service를 Control Tower 동기 port로 변환한다."""

from collections.abc import Callable
from typing import Any

import rclpy
from trihouse_interfaces.srv import EstimateTaskEnergy

from .energy_estimator import EstimateRequest, RmfEstimateResponse


class RosEstimateService:
    """비동기 ROS client를 timeout이 있는 동기 callable로 제공한다."""

    def __init__(
        self,
        node: Any,
        service_name: str = "/trihouse/rmf/estimate_task_energy",
        *,
        spin_until_future_complete: Callable[..., None] = (
            rclpy.spin_until_future_complete
        ),
    ) -> None:
        self._node = node
        self._client = node.create_client(EstimateTaskEnergy, service_name)
        self._spin_until_future_complete = spin_until_future_complete

    def __call__(
        self, request: EstimateRequest, timeout_s: float
    ) -> RmfEstimateResponse:
        ros_request = EstimateTaskEnergy.Request()
        ros_request.robot_id = request.robot_id
        ros_request.task_id = request.task_id
        ros_request.map_revision = request.map_revision
        ros_request.waypoint_ids = list(request.waypoint_ids)
        ros_request.expected_loading_duration_s = request.expected_loading_duration_s
        ros_request.expected_handover_duration_s = request.expected_handover_duration_s
        ros_request.task_time_buffer_s = request.task_time_buffer_s

        future = self._client.call_async(ros_request)
        self._spin_until_future_complete(
            self._node, future, timeout_sec=timeout_s
        )
        if not future.done():
            future.cancel()
            raise TimeoutError("RMF energy service timed out")
        result = future.result()
        if result is None:
            raise RuntimeError("RMF energy service returned no response")
        return RmfEstimateResponse(
            result.success,
            result.travel_duration_s,
            result.total_duration_s,
            result.change_in_charge,
            result.finish_state_of_charge,
            result.reason_code,
            result.detail,
        )
