"""검증된 파지·인수인계 단계만 결정하는 장비 독립 OMX 작업 정책.

OMX/MoveIt adapter가 반환 명령을 실행하고 결과를 보고한다. 명령 전송만으로 성공을 가정하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class OmxState(StrEnum):
    RECOGNITION_REQUIRED = 'RECOGNITION_REQUIRED'
    PICK_AUTHORIZED = 'PICK_AUTHORIZED'
    READY_TO_LOAD = 'READY_TO_LOAD'
    PAUSED_FOR_PERSON = 'PAUSED_FOR_PERSON'
    ITEM_HELD = 'ITEM_HELD'
    HANDOVER_CONFIRMED = 'HANDOVER_CONFIRMED'
    CANCELLED = 'CANCELLED'


@dataclass(frozen=True)
class OmxResult:
    accepted: bool
    state: OmxState
    reason: str = ''
    next_offset: tuple[float, float] | None = None


@dataclass
class _Job:
    order_id: str
    expected_items: tuple[str, ...]
    state: OmxState = OmxState.RECOGNITION_REQUIRED
    picked_items: set[str] = field(default_factory=set)
    retry_index: dict[str, int] = field(default_factory=dict)


class OmxWorkflow:
    def __init__(self, *, retry_offsets: tuple[tuple[float, float], ...]) -> None:
        if not retry_offsets:
            raise ValueError('at least one registered pick offset is required')
        self._retry_offsets = retry_offsets
        self._jobs: dict[str, _Job] = {}
        self._temporary_slots: dict[str, tuple[str, str]] = {}

    def start(self, job_id: str, *, order_id: str, expected_items: tuple[str, ...]) -> None:
        if not expected_items:
            raise ValueError('an OMX job needs at least one expected item')
        if len(set(expected_items)) != len(expected_items):
            raise ValueError('expected items must be unique')
        self._jobs[job_id] = _Job(order_id, expected_items)

    def authorize_pick(self, job_id: str, item_id: str, *, qr_matches: bool, marker_valid: bool) -> OmxResult:
        job = self._job(job_id)
        if job.state == OmxState.PAUSED_FOR_PERSON:
            return OmxResult(False, job.state, 'person safety pause active')
        if item_id not in job.expected_items:
            return OmxResult(False, job.state, 'item is not reserved for this job')
        if not qr_matches or not marker_valid:
            job.state = OmxState.RECOGNITION_REQUIRED
            return OmxResult(False, job.state, 'QR or marker validation failed')
        job.state = OmxState.PICK_AUTHORIZED
        job.retry_index.setdefault(item_id, 0)
        return OmxResult(True, job.state, next_offset=self._retry_offsets[job.retry_index[item_id]])

    def pick_failed(self, job_id: str, item_id: str) -> OmxResult:
        job = self._job(job_id)
        retry = job.retry_index.get(item_id)
        if job.state != OmxState.PICK_AUTHORIZED or retry is None:
            return OmxResult(False, job.state, 'pick was not authorized')
        retry += 1
        job.retry_index[item_id] = retry
        if retry >= len(self._retry_offsets):
            job.state = OmxState.ITEM_HELD
            return OmxResult(False, job.state, 'pick retry exhausted')
        job.state = OmxState.RECOGNITION_REQUIRED
        return OmxResult(False, job.state, 'reobserve before retry', self._retry_offsets[retry])

    def pick_succeeded(self, job_id: str, item_id: str) -> OmxResult:
        job = self._job(job_id)
        if job.state != OmxState.PICK_AUTHORIZED:
            return OmxResult(False, job.state, 'pick was not authorized')
        job.picked_items.add(item_id)
        job.state = OmxState.READY_TO_LOAD
        return OmxResult(True, job.state)

    def reserve_temporary_slot(self, job_id: str, item_id: str, available_slots: tuple[str, ...]) -> str:
        job = self._job(job_id)
        if item_id not in job.expected_items:
            raise ValueError('item is not part of this job')
        for slot in available_slots:
            owner = self._temporary_slots.get(slot)
            if owner is None:
                self._temporary_slots[slot] = (job_id, item_id)
                return slot
            if owner == (job_id, item_id):
                return slot
        raise ValueError('no temporary slot available')

    def person_entered(self, job_id: str) -> OmxResult:
        job = self._job(job_id)
        job.state = OmxState.PAUSED_FOR_PERSON
        return OmxResult(True, job.state, 'hold gripper and stop arm motion')

    def cancel(self, job_id: str) -> OmxResult:
        """Release only bookkeeping reservations; hardware safe-stop is adapter-owned."""
        job = self._job(job_id)
        for slot, owner in tuple(self._temporary_slots.items()):
            if owner[0] == job_id:
                del self._temporary_slots[slot]
        job.state = OmxState.CANCELLED
        return OmxResult(True, job.state)

    def person_cleared(self, job_id: str, *, consecutive_safe_frames: bool) -> OmxResult:
        job = self._job(job_id)
        if job.state != OmxState.PAUSED_FOR_PERSON:
            return OmxResult(False, job.state, 'no person pause is active')
        if not consecutive_safe_frames:
            return OmxResult(False, job.state, 'safe-frame condition not satisfied')
        job.state = OmxState.READY_TO_LOAD if job.picked_items else OmxState.RECOGNITION_REQUIRED
        return OmxResult(True, job.state)

    def confirm_handover(self, job_id: str, *, loaded_items: tuple[str, ...], gripper_open: bool, retreated: bool) -> OmxResult:
        job = self._job(job_id)
        if set(loaded_items) != set(job.expected_items):
            return OmxResult(False, job.state, 'loaded item list does not match reservation')
        if not gripper_open or not retreated:
            return OmxResult(False, job.state, 'gripper open and safe retreat are required')
        job.state = OmxState.HANDOVER_CONFIRMED
        return OmxResult(True, job.state)

    def state_of(self, job_id: str) -> OmxState:
        return self._job(job_id).state

    def _job(self, job_id: str) -> _Job:
        try:
            return self._jobs[job_id]
        except KeyError as error:
            raise ValueError(f'unknown OMX job {job_id}') from error
