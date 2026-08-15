"""Read-only Pinky runtime profile exposed through the public Gateway API."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


NAV2_SOURCE = Path("pinky_pro/pinky_navigation/params/nav2_params.yaml")
PINKY_SOURCE = Path("pinky_pro/pinky_bringup/config/pinky_params.yaml")


def _value(mapping: object, *keys: str) -> Any:
    current = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return deepcopy(current)


class RuntimeProfileProvider:
    """Load the two pinned pinky_pro YAML sources without accepting UI overrides."""

    def __init__(self, repository_root: Path | None = None):
        self.repository_root = (
            repository_root.resolve()
            if repository_root is not None
            else Path(__file__).resolve().parents[2]
        )

    def load(self) -> dict[str, Any]:
        source_names = [NAV2_SOURCE.as_posix(), PINKY_SOURCE.as_posix()]
        source_bytes = [
            (self.repository_root / source_name).read_bytes()
            for source_name in source_names
        ]
        source_hashes = [hashlib.sha256(value).hexdigest() for value in source_bytes]
        profile_hash = hashlib.sha256(
            json.dumps(
                list(zip(source_names, source_hashes, strict=True)),
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        nav2 = yaml.safe_load(source_bytes[0]) or {}
        pinky = yaml.safe_load(source_bytes[1]) or {}
        controller = _value(nav2, "controller_server", "ros__parameters") or {}
        follow_path = _value(controller, "FollowPath") or {}
        planner = _value(nav2, "planner_server", "ros__parameters") or {}
        planner_names = _value(planner, "planner_plugins") or []
        planner_name = planner_names[0] if planner_names else None
        planner_config = (
            _value(planner, planner_name) if isinstance(planner_name, str) else {}
        ) or {}
        local_costmap = (
            _value(nav2, "local_costmap", "local_costmap", "ros__parameters") or {}
        )
        global_costmap = (
            _value(nav2, "global_costmap", "global_costmap", "ros__parameters")
            or {}
        )
        goal = _value(controller, "general_goal_checker") or {}
        progress = _value(controller, "progress_checker") or {}
        velocity = _value(nav2, "velocity_smoother", "ros__parameters") or {}
        bringup = _value(pinky, "pinky_bringup", "ros__parameters") or {}

        footprint_value = local_costmap.get("footprint")
        footprint = None
        if isinstance(footprint_value, str):
            decoded = yaml.safe_load(footprint_value)
            if isinstance(decoded, list):
                footprint = decoded
        elif isinstance(footprint_value, list):
            footprint = deepcopy(footprint_value)
        dimensions = None
        if footprint and all(
            isinstance(point, list) and len(point) == 2 for point in footprint
        ):
            xs = [float(point[0]) for point in footprint]
            ys = [float(point[1]) for point in footprint]
            dimensions = {
                "length": max(xs) - min(xs),
                "width": max(ys) - min(ys),
            }

        max_velocity = velocity.get("max_velocity")
        linear_speed = None
        angular_speed = None
        if isinstance(max_velocity, list):
            if max_velocity:
                linear_speed = max_velocity[0]
            if len(max_velocity) >= 3:
                angular_speed = max_velocity[2]

        return {
            "profile_name": "pinky_pro simulation profile",
            "profile_hash": profile_hash,
            "source_files": source_names,
            "controller": {
                "plugin": follow_path.get("plugin"),
                "controller_frequency_hz": controller.get("controller_frequency"),
                "desired_linear_velocity_mps": follow_path.get(
                    "desired_linear_vel"
                ),
            },
            "planner": {
                "plugin": planner_config.get("plugin"),
                "expected_frequency_hz": planner.get(
                    "expected_planner_frequency"
                ),
                "tolerance_m": planner_config.get("tolerance"),
            },
            "local_costmap": {
                "resolution": local_costmap.get("resolution"),
                "width_m": local_costmap.get("width"),
                "height_m": local_costmap.get("height"),
                "inflation_radius_m": _value(
                    local_costmap, "inflation_layer", "inflation_radius"
                ),
                "cost_scaling_factor": _value(
                    local_costmap, "inflation_layer", "cost_scaling_factor"
                ),
            },
            "global_costmap": {
                "resolution": global_costmap.get("resolution"),
                "width_m": global_costmap.get("width"),
                "height_m": global_costmap.get("height"),
                "inflation_radius_m": _value(
                    global_costmap, "inflation_layer", "inflation_radius"
                ),
                "cost_scaling_factor": _value(
                    global_costmap, "inflation_layer", "cost_scaling_factor"
                ),
            },
            "robot": {
                "footprint": footprint,
                "dimensions_m": dimensions,
                # robot_radius is commented out in the pinned source. Do not infer it.
                "robot_radius_m": local_costmap.get("robot_radius"),
            },
            "max_speeds": {
                "linear_mps": linear_speed,
                "angular_radps": angular_speed,
            },
            "goal_tolerances": {
                "xy_m": goal.get("xy_goal_tolerance"),
                "yaw_rad": goal.get("yaw_goal_tolerance"),
            },
            "progress_tolerances": {
                "required_movement_radius_m": progress.get(
                    "required_movement_radius"
                ),
                "movement_time_allowance_s": progress.get(
                    "movement_time_allowance"
                ),
            },
            "wheel_parameters": {
                "wheel_radius_m": bringup.get("wheel_radius"),
                "wheel_separation_m": bringup.get("wheel_separation"),
            },
        }
