"""Synchronous ROS Action client used by the central Executor worker."""

from __future__ import annotations

import json
import re
from typing import Any


_DEVICE_ID = re.compile(r"OMX_[0-9]{2,}")


def action_endpoint_for_device(device_id: str) -> str:
    """Derive the only allowed ROS route from the canonical DB device ID."""
    if _DEVICE_ID.fullmatch(device_id) is None:
        raise ValueError(f"invalid canonical OMX device ID: {device_id!r}")
    return f"/{device_id.lower()}/execute"


class RosOmxActionExecutor:
    """Block one polling worker until its device-specific Action completes."""

    def __init__(self, node: object, *, device_id: str, timeout_s: float = 300.0) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        from rclpy.action import ActionClient
        from trihouse_interfaces.action import ExecuteOmx

        self._rclpy = __import__("rclpy")
        self._action_type = ExecuteOmx
        self._client = ActionClient(
            node, ExecuteOmx, action_endpoint_for_device(device_id)
        )
        self._node = node
        self._device_id = device_id
        self._timeout_s = timeout_s

    def execute(self, command: dict[str, object]) -> dict[str, Any]:
        if command.get("omx_id") != self._device_id:
            raise RuntimeError("DEVICE_MISMATCH")
        if not self._client.wait_for_server(timeout_sec=self._timeout_s):
            raise TimeoutError(f"{action_endpoint_for_device(self._device_id)} unavailable")
        goal = self._action_type.Goal()
        goal.command_json = json.dumps(
            command, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        sent = self._client.send_goal_async(goal)
        self._rclpy.spin_until_future_complete(
            self._node, sent, timeout_sec=self._timeout_s
        )
        handle = sent.result()
        if handle is None or not handle.accepted:
            raise RuntimeError("OMX Action goal rejected")
        completed = handle.get_result_async()
        self._rclpy.spin_until_future_complete(
            self._node, completed, timeout_sec=self._timeout_s
        )
        wrapped = completed.result()
        if wrapped is None:
            raise TimeoutError("OMX Action result timeout")
        result = wrapped.result
        try:
            body = json.loads(result.result_json)
        except json.JSONDecodeError as error:
            raise RuntimeError("OMX Action returned invalid result JSON") from error
        if not result.success:
            reason = body.get("reason_code", "OMX_EXECUTION_FAILED")
            raise RuntimeError(f"{reason} (code={result.code})")
        if not isinstance(body, dict):
            raise RuntimeError("OMX Action result must be a JSON object")
        body["success"] = True
        return body


__all__ = ["RosOmxActionExecutor", "action_endpoint_for_device"]
