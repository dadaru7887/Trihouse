"""ROS 2 ExecuteOmx server forwarding one goal to the local LeRobot worker."""

from __future__ import annotations

import json
import os
import socket

import rclpy
from rclpy.action import ActionServer
from rclpy.node import Node
from trihouse_interfaces.action import ExecuteOmx

from .action_client import action_endpoint_for_device


class UnixWorkerClient:
    def __init__(self, socket_path: str, *, timeout_s: float) -> None:
        self._socket_path = socket_path
        self._timeout_s = timeout_s

    def execute(self, command: dict[str, object]) -> dict[str, object]:
        frame = json.dumps(
            command, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8") + b"\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(self._timeout_s)
            client.connect(self._socket_path)
            client.sendall(frame)
            response = b""
            while not response.endswith(b"\n"):
                chunk = client.recv(65536)
                if not chunk:
                    raise RuntimeError("worker closed without a result")
                response += chunk
                if len(response) > 1_048_576:
                    raise RuntimeError("worker result is too large")
        decoded = json.loads(response)
        if not isinstance(decoded, dict):
            raise RuntimeError("worker result must be an object")
        return decoded


class OmxActionServer(Node):
    def __init__(self) -> None:
        super().__init__("omx_action_server")
        self.declare_parameter("device_id", os.environ.get("DEVICE_ID", ""))
        self.declare_parameter(
            "worker_socket",
            os.environ.get("OMX_WORKER_SOCKET", "/run/trihouse-omx/worker.sock"),
        )
        self.declare_parameter("worker_timeout_s", 300.0)
        self._device_id = str(self.get_parameter("device_id").value)
        if not self._device_id:
            raise RuntimeError("device_id is required")
        self._worker = UnixWorkerClient(
            str(self.get_parameter("worker_socket").value),
            timeout_s=float(self.get_parameter("worker_timeout_s").value),
        )
        self._server = ActionServer(
            self,
            ExecuteOmx,
            action_endpoint_for_device(self._device_id),
            self._execute,
        )

    def _execute(self, goal_handle):  # noqa: ANN001
        result = ExecuteOmx.Result()
        try:
            command = json.loads(goal_handle.request.command_json)
            if not isinstance(command, dict):
                raise ValueError("command_json must contain an object")
            if command.get("omx_id") != self._device_id:
                result.code = ExecuteOmx.Result.CODE_DEVICE_MISMATCH
                result.result_json = json.dumps({"reason_code": "DEVICE_MISMATCH"})
                goal_handle.abort()
                return result
            body = self._worker.execute(command)
            result.success = body.get("success") is True
            result.code = (
                ExecuteOmx.Result.CODE_OK
                if result.success
                else ExecuteOmx.Result.CODE_EXECUTION_FAILED
            )
            result.result_json = json.dumps(body, ensure_ascii=False, sort_keys=True)
            if result.success:
                goal_handle.succeed()
            else:
                goal_handle.abort()
            return result
        except (ValueError, json.JSONDecodeError) as error:
            result.code = ExecuteOmx.Result.CODE_INVALID_COMMAND
            result.result_json = json.dumps(
                {"reason_code": "INVALID_COMMAND", "detail": str(error)}
            )
        except Exception as error:  # noqa: BLE001
            result.code = ExecuteOmx.Result.CODE_NOT_READY
            result.result_json = json.dumps(
                {"reason_code": "WORKER_UNAVAILABLE", "detail": str(error)}
            )
        goal_handle.abort()
        return result


def main() -> None:
    rclpy.init()
    node = OmxActionServer()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
