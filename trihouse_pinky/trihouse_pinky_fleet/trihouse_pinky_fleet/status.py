"""SR_03 로봇 상태를 조합하는 순수 정책. ROS message 변환은 node 경계가 맡는다."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatusInputs:
    robot_id: str
    job_id: str = ""
    scan_fresh: bool = True
    odom_fresh: bool = True
    battery_fresh: bool = True


@dataclass(frozen=True)
class StatusSummary:
    robot_id: str
    job_id: str
    ready: bool
    errors: tuple[str, ...]


def build_status(inputs: StatusInputs) -> StatusSummary:
    """A robot with stale motion/safety/battery telemetry is not assignable."""
    errors = tuple(
        name for name, fresh in (
            ("scan_stale", inputs.scan_fresh),
            ("odom_stale", inputs.odom_fresh),
            ("battery_stale", inputs.battery_fresh),
        ) if not fresh
    )
    return StatusSummary(inputs.robot_id, inputs.job_id, not errors, errors)
