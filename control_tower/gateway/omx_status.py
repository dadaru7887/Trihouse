"""OMX 상태를 1초 heartbeat 또는 상태 변경 즉시 발행하는 정책."""

from dataclasses import dataclass


@dataclass(frozen=True)
class OmxStatus:
    robot_id: str
    job_id: str
    stage: str
    ready: bool
    motion_state: str
    grasped: bool
    loaded: bool
    safety_fault: bool
    error: str


class OmxStatusPublisher:
    def __init__(self, *, period_s: float) -> None:
        if period_s <= 0:
            raise ValueError('period_s must be positive')
        self._period_s = period_s
        self._last_status: OmxStatus | None = None
        self._last_sent_at_s: float | None = None

    def should_publish(self, status: OmxStatus, *, now_s: float) -> bool:
        if now_s < 0:
            raise ValueError('now_s must be non-negative')
        changed = status != self._last_status
        due = self._last_sent_at_s is None or now_s - self._last_sent_at_s >= self._period_s
        if not changed and not due:
            return False
        self._last_status, self._last_sent_at_s = status, now_s
        return True
