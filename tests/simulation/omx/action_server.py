"""No-motion ExecuteOmx Action server for integration tests."""

from __future__ import annotations

import json
import os

import rclpy
from rclpy.action import ActionServer
from rclpy.node import Node
from trihouse_interfaces.action import ExecuteOmx

from trihouse_omx_adapter.action_client import action_endpoint_for_device


class SimulationOmxActionServer(Node):
    def __init__(self) -> None:
        super().__init__("simulation_omx_action_server")
        self.declare_parameter("device_id", os.environ.get("DEVICE_ID", ""))
        self._device_id = str(self.get_parameter("device_id").value)
        self._results: dict[str, tuple[str, dict[str, object]]] = {}
        self._server = ActionServer(
            self,
            ExecuteOmx,
            action_endpoint_for_device(self._device_id),
            self._execute,
        )

    def _execute(self, goal_handle):  # noqa: ANN001
        result = ExecuteOmx.Result()
        command = json.loads(goal_handle.request.command_json)
        if command.get("omx_id") != self._device_id:
            result.code = ExecuteOmx.Result.CODE_DEVICE_MISMATCH
            result.result_json = json.dumps({"reason_code": "DEVICE_MISMATCH"})
            goal_handle.abort()
            return result
        canonical = json.dumps(command, ensure_ascii=False, sort_keys=True)
        cached = self._results.get(command["command_uuid"])
        if cached is not None and cached[0] != canonical:
            result.code = ExecuteOmx.Result.CODE_INVALID_COMMAND
            result.result_json = json.dumps({"reason_code": "COMMAND_UUID_CONFLICT"})
            goal_handle.abort()
            return result
        body = cached[1] if cached else self._simulate(command)
        self._results[command["command_uuid"]] = (canonical, body)
        result.success = True
        result.code = ExecuteOmx.Result.CODE_OK
        result.result_json = json.dumps(body, ensure_ascii=False, sort_keys=True)
        goal_handle.succeed()
        return result

    @staticmethod
    def _simulate(command: dict[str, object]) -> dict[str, object]:
        return {
            "success": True,
            "policy_completed": True,
            "policy_name": "simulation_act",
            "policy_version": "v1",
            "model_name": "no_motion",
            "model_version": "v1",
            "items": [
                {
                    "job_item_id": item["job_item_id"],
                    "grasp_confirmed": True,
                    "release_confirmed": True,
                    "policy_completed": True,
                    "evidence_refs": [f"simulation:{command['command_uuid']}"],
                }
                for item in command["items"]
            ]
            if command["kind"] == "load"
            else [],
        }


def main() -> None:
    rclpy.init()
    node = SimulationOmxActionServer()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
