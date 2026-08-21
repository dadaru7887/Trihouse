"""Long-lived OMX/LeRobot runtime owned only by the Python 3.10 worker."""

from __future__ import annotations

import atexit
import os
import time
from pathlib import Path
from typing import Any

from .product_policy_catalog import ProductPolicyCatalog


class HardwareRuntime:
    """Prepare resources once, then execute ACT pick-and-place per item unit."""

    def __init__(
        self,
        *,
        device_id: str,
        temperature_zones: frozenset[str],
        serial_device: str,
        front_camera: str,
        wrist_camera: str,
        calibration_id: str,
        catalog: ProductPolicyCatalog,
        episode_steps: int,
        fps: float,
    ) -> None:
        self._device_id = device_id
        self._zones = temperature_zones
        self._serial = serial_device
        self._front_camera = front_camera
        self._wrist_camera = wrist_camera
        self._calibration_id = calibration_id
        self._catalog = catalog
        self._episode_steps = episode_steps
        self._fps = fps
        self._robot = None
        self._dataset_features = None
        self._prepared: tuple[int, int, str, tuple[tuple[str, int], ...]] | None = None

    @classmethod
    def from_environment(cls, *, device_id: str) -> "HardwareRuntime":
        required = {
            name: os.environ.get(name, "").strip()
            for name in (
                "OMX_TEMPERATURE_ZONES",
                "OMX_SERIAL_DEVICE",
                "OMX_FRONT_CAMERA",
                "OMX_WRIST_CAMERA",
                "OMX_CALIBRATION_ID",
                "OMX_PRODUCT_POLICIES",
            )
        }
        missing = sorted(name for name, value in required.items() if not value)
        if missing:
            raise RuntimeError(f"missing OMX environment: {', '.join(missing)}")
        return cls(
            device_id=device_id,
            temperature_zones=frozenset(
                zone.strip()
                for zone in required["OMX_TEMPERATURE_ZONES"].split(",")
                if zone.strip()
            ),
            serial_device=required["OMX_SERIAL_DEVICE"],
            front_camera=required["OMX_FRONT_CAMERA"],
            wrist_camera=required["OMX_WRIST_CAMERA"],
            calibration_id=required["OMX_CALIBRATION_ID"],
            catalog=ProductPolicyCatalog.load(Path(required["OMX_PRODUCT_POLICIES"])),
            episode_steps=int(os.environ.get("OMX_EPISODE_STEPS", "900")),
            fps=float(os.environ.get("OMX_POLICY_FPS", "15")),
        )

    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        zone = str(command["temperature_zone"])
        if command["omx_id"] != self._device_id:
            raise RuntimeError("DEVICE_MISMATCH")
        if zone not in self._zones:
            raise RuntimeError(f"ZONE_MISMATCH:{zone}")
        signature = self._signature(command)
        policies = [
            self._catalog.lookup(item["product_code"], temperature_zone=zone)
            for item in command["items"]
        ]
        kind = command["kind"]
        if kind == "prepare":
            self._connect_once()
            self._prepared = signature
            return {
                "success": True,
                "policy_completed": True,
                "state": "omx_ready",
                "items": [],
            }
        if kind in {"hold", "reset"}:
            self._prepared = None
            return {
                "success": True,
                "policy_completed": True,
                "state": "held" if kind == "hold" else "idle",
                "items": [],
            }
        if kind != "load" or self._prepared != signature:
            raise RuntimeError("PREPARE_MISMATCH")
        self._connect_once()
        results = [
            self._run_item(command, item, policy)
            for item, policy in zip(command["items"], policies, strict=True)
        ]
        success = all(
            result["grasp_confirmed"] and result["release_confirmed"]
            for result in results
        )
        self._prepared = None
        return {
            "success": success,
            "policy_completed": success,
            "policy_name": "act",
            "policy_version": ",".join(policy.policy_repo_id for policy in policies),
            "model_name": "lerobot_act",
            "model_version": "catalog_v1",
            "items": results,
        }

    @staticmethod
    def _signature(command: dict[str, Any]) -> tuple[int, int, str, tuple[tuple[str, int], ...]]:
        return (
            int(command["job_id"]),
            int(command["assignment_revision"]),
            str(command["temperature_zone"]),
            tuple(
                (str(item["product_code"]), int(item["quantity"]))
                for item in command["items"]
            ),
        )

    def _connect_once(self) -> None:
        if self._robot is not None:
            return
        from . import policy_runtime, robot_session

        robot = robot_session.build_robot(
            port=self._serial,
            robot_id=self._calibration_id,
            cameras=(
                robot_session.CameraSpec("front", self._front_camera),
                robot_session.CameraSpec("wrist", self._wrist_camera),
            ),
        )
        robot.connect(calibrate=True)
        self._robot = robot
        self._dataset_features = policy_runtime.build_dataset_features(robot)
        atexit.register(self._disconnect)

    def _disconnect(self) -> None:
        if self._robot is not None and self._robot.is_connected:
            self._robot.disconnect()

    def _run_item(self, command, item, policy):  # noqa: ANN001
        units = [self._run_unit(policy) for _ in range(int(item["quantity"]))]
        grasped = all(unit["grasp_confirmed"] for unit in units)
        released = all(unit["release_confirmed"] for unit in units)
        return {
            "job_item_id": int(item["job_item_id"]),
            "product_code": str(item["product_code"]),
            "quantity": int(item["quantity"]),
            "grasp_confirmed": grasped,
            "release_confirmed": released,
            "policy_completed": grasped and released,
            "unit_results": units,
            "evidence_refs": [
                f"omx:{self._device_id}:{command['command_uuid']}:{item['job_item_id']}"
            ],
        }

    def _run_unit(self, policy):  # noqa: ANN001
        from . import grasp_check, policy_runtime

        loaded = policy_runtime.load_policy(policy.policy_repo_id)
        loaded.reset()
        grasp = grasp_check.Debouncer()
        release = grasp_check.Debouncer()
        grasped = False
        released = False
        grasp_step = None
        release_step = None
        settle_until = None
        interval_s = 1.0 / self._fps

        for step in range(self._episode_steps):
            started = time.perf_counter()
            action = policy_runtime.infer_step(
                self._robot,
                loaded,
                self._dataset_features,
                task=policy.policy_key,
            )
            self._robot.send_action(action)
            remaining = interval_s - (time.perf_counter() - started)
            if remaining > 0:
                time.sleep(remaining)
            current, position = grasp_check.read_gripper(self._robot)
            if step < 30:
                continue
            if not grasped and grasp.update(
                grasp_check.evaluate_grasp(current, position).grasped
            ):
                grasped = True
                grasp_step = step
            elif grasped and not released and release.update(
                grasp_check.evaluate_release(current, position).released
            ):
                released = True
                release_step = step
                settle_until = step + 120
            elif released and step >= settle_until:
                break

        return {
            "grasp_confirmed": grasped,
            "release_confirmed": released,
            "policy_completed": grasped and released,
            "grasp_step": grasp_step,
            "release_step": release_step,
        }
