"""물리 인수인계 전에 Pinky·OMX 두 준비 상태를 함께 확인하는 gate."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _Handover:
    pinky_id: str
    omx_id: str
    ready_roles: set[str] = field(default_factory=set)


class HandoverGate:
    def __init__(self) -> None:
        self._handovers: dict[str, _Handover] = {}

    def expect(self, job_id: str, *, pinky_id: str, omx_id: str) -> None:
        if not all((job_id, pinky_id, omx_id)):
            raise ValueError('job, Pinky, and OMX IDs are required')
        self._handovers[job_id] = _Handover(pinky_id, omx_id)

    def mark_ready(self, job_id: str, *, robot_id: str, role: str) -> bool:
        handover = self._handover(job_id)
        expected = {'PINKY': handover.pinky_id, 'OMX': handover.omx_id}
        if expected.get(role) != robot_id:
            return False
        handover.ready_roles.add(role)
        return self.can_start(job_id)

    def can_start(self, job_id: str) -> bool:
        return self._handover(job_id).ready_roles == {'PINKY', 'OMX'}

    def reassign_pinky(self, job_id: str, *, pinky_id: str) -> None:
        handover = self._handover(job_id)
        handover.pinky_id = pinky_id
        handover.ready_roles.clear()

    def cancel(self, job_id: str) -> None:
        self._handovers.pop(job_id, None)

    def _handover(self, job_id: str) -> _Handover:
        try:
            return self._handovers[job_id]
        except KeyError as error:
            raise ValueError(f'unknown handover job {job_id}') from error
