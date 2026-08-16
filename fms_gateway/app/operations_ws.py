"""운영 화면이 구독하는 공개 WebSocket 투영.

UI는 DB·RMF·ROS를 직접 보지 않는다. 이 모듈이 한 개의 불변 스냅숏과 그
뒤의 증분 이벤트만 직렬화한다. 지도 화면의 1차 정보는 Nav2가 실제로 계산한
전역/지역 경로와 로봇이 지나온 궤적이며, 내부 bootstrap graph는 절대
내보내지 않는다. RMF timed trajectory는 진단 토글용 선택 필드다.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Protocol


# UI가 구독할 수 있는 이벤트 종류. 목록 밖의 이름은 내보내지 않는다.
OPERATIONS_EVENT_KINDS = (
    "SNAPSHOT",
    "ROBOT_UPDATED",
    "PATH_UPDATED",
    "PATH_SCHEDULE_MISMATCH",
    "COSTMAP_UPDATED",
    "BOTTLENECK_LEASE",
    "RMF_CONFLICT",
    "RMF_DELAY",
    "CAMERA_STATUS",
    "JOB_UPDATED",
    "INCIDENT_OPEN",
    "INCIDENT_DECIDED",
)

# 운영자 레이어가 아니므로 어떤 메시지에도 실리지 않는다.
FORBIDDEN_PROJECTION_KEYS = ("bootstrap_graph", "nav_graph", "lanes")


class OperationsSource(Protocol):
    def snapshot(self) -> Any: ...

    def drain_events(self) -> tuple[Any, ...]: ...


@dataclass
class OperationsBroadcaster:
    """구독자에게 스냅숏 한 번과 이후 증분 이벤트를 보낸다."""

    source: OperationsSource
    _subscribers: list[asyncio.Queue] = field(default_factory=list)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        queue.put_nowait(self.snapshot_message())
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def snapshot_message(self) -> dict[str, Any]:
        return _guard({"kind": "SNAPSHOT", "payload": _project(self.source.snapshot())})

    def publish_pending(self) -> list[dict[str, Any]]:
        """모아 둔 이벤트를 구독자 전원에게 같은 순서로 보낸다."""
        messages = [
            _guard({"kind": event.kind, "entity_id": event.entity_id})
            for event in self.source.drain_events()
            if event.kind in OPERATIONS_EVENT_KINDS
        ]
        for queue in self._subscribers:
            for message in messages:
                queue.put_nowait(message)
        return messages


def _project(snapshot: Any) -> dict[str, Any]:
    return {
        "robots": [
            {
                "robot_id": robot.robot_id,
                "x": robot.x,
                "y": robot.y,
                "yaw": robot.yaw,
                "battery_percent": robot.battery_percent,
                "safety_state": robot.safety_state,
                "job_id": robot.job_id,
                "stage": robot.stage,
                "error": robot.error,
            }
            for robot in snapshot.robots
        ],
        "paths": [
            {
                "robot_id": path.robot_id,
                "map_revision": path.map_revision,
                "nav2_global_path": [list(point) for point in path.nav2_global_path],
                "nav2_local_path": [list(point) for point in path.nav2_local_path],
                "actual_trail": [list(point) for point in path.actual_trail],
                # 진단 토글이 켜졌을 때만 UI가 그린다.
                "rmf_timed_trajectory": [
                    list(point) for point in path.rmf_timed_trajectory
                ],
                "goal_pose": list(path.goal_pose),
            }
            for path in getattr(snapshot, "paths", ())
        ],
        "cameras": [
            {
                "camera_id": camera.camera_id,
                "role": camera.role,
                "attached_to": camera.attached_to,
                "mediamtx_path": camera.mediamtx_path,
                # P1 캘리브레이션 전까지 좌표는 없다.
                "map_pose": camera.map_pose,
            }
            for camera in getattr(snapshot, "cameras", ())
        ],
        "jobs": [
            {
                "job_id": job.job_id,
                "order_id": job.order_id,
                "item_ids": list(job.item_ids),
                "robot_id": job.robot_id,
                "stage": job.stage,
                "state": job.state,
            }
            for job in snapshot.jobs
        ],
        "incidents": [
            {
                "incident_id": incident.incident_id,
                "camera_id": incident.camera_id,
                "location_id": incident.location_id,
                "occurred_at_s": incident.occurred_at_s,
                "acknowledged": incident.acknowledged,
            }
            for incident in snapshot.incidents
        ],
        "bootstrap_graph_visible": False,
    }


def _guard(message: dict[str, Any]) -> dict[str, Any]:
    """운영자에게 내보내면 안 되는 키가 실렸는지 확인한다."""
    encoded = json.dumps(message, ensure_ascii=False)
    for key in FORBIDDEN_PROJECTION_KEYS:
        if f'"{key}"' in encoded:
            raise ValueError(f"{key} must never be projected to the operations UI")
    return message


__all__ = [
    "FORBIDDEN_PROJECTION_KEYS",
    "OPERATIONS_EVENT_KINDS",
    "OperationsBroadcaster",
    "OperationsSource",
]
