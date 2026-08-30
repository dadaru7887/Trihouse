"""Navigation facts joined with a 5080 perception frame."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import time
from typing import Any, Callable
from urllib import request


@dataclass(frozen=True)
class NavigationContext:
    device_id: str
    map_name: str
    map_revision: str
    robot_pose: tuple[float, float, float]
    goal_pose: tuple[float, float]
    navigation_state: str
    stuck_seconds: float


def _get_json(url: str) -> dict[str, Any]:
    with request.urlopen(url, timeout=2.0) as response:
        return json.loads(response.read())


class GatewayNavigationContextSource:
    """Add a progress timer to the Gateway's latest robot/goal projection."""

    def __init__(
        self,
        gateway_url: str,
        device_id: str,
        *,
        transport: Callable[[str], dict[str, Any]] = _get_json,
        clock: Callable[[], float] = time.monotonic,
        progress_threshold_m: float = 0.02,
    ):
        self.url = (
            gateway_url.rstrip("/")
            + f"/internal/v1/recovery/navigation-context/{device_id}"
        )
        self.transport = transport
        self.clock = clock
        self.progress_threshold_m = progress_threshold_m
        self._last_pose: tuple[float, float, float] | None = None
        self._last_progress_at: float | None = None

    def get(self) -> NavigationContext:
        payload = self.transport(self.url)
        pose = tuple(float(value) for value in payload["robot_pose"])
        goal = tuple(float(value) for value in payload["goal_pose"])
        if len(pose) != 3 or len(goal) != 2:
            raise ValueError("Gateway navigation context has invalid pose dimensions")
        now = self.clock()
        progressed = self._last_pose is None or math.hypot(
            pose[0] - self._last_pose[0], pose[1] - self._last_pose[1]
        ) >= self.progress_threshold_m
        if progressed or payload["navigation_state"] != "navigating":
            self._last_progress_at = now
        self._last_pose = pose
        stuck_seconds = max(0.0, now - (self._last_progress_at or now))
        navigation_state = str(payload["navigation_state"])
        if navigation_state == "navigating" and stuck_seconds >= 3.0:
            navigation_state = "stuck"
        return NavigationContext(
            device_id=str(payload["device_id"]),
            map_name=str(payload["map_name"]),
            map_revision=str(payload["map_revision"]),
            robot_pose=pose,
            goal_pose=goal,
            navigation_state=navigation_state,
            stuck_seconds=stuck_seconds,
        )
