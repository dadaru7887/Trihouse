"""동일 배정 단계에서 Pinky·OMX 성공 완료를 한 번만 결합하는 Gate."""

from dataclasses import dataclass, field

from .execution_result import ActorRole, CompletionEvent


@dataclass(frozen=True)
class GateDecision:
    """완료 이벤트가 Gate에 반영됐는지와 release 여부."""

    accepted: bool
    duplicate: bool = False
    released: bool = False
    reason_code: str = ""


@dataclass
class _Handover:
    job_step_id: str
    assignment_revision: int
    pinky_id: str
    omx_id: str
    completed_roles: set[ActorRole] = field(default_factory=set)
    processed_event_ids: set[str] = field(default_factory=set)
    released: bool = False


class HandoverGate:
    """두 역할의 완료 여부만 모으며 작업 상태 전이는 소유하지 않는다."""

    def __init__(self) -> None:
        self._handovers: dict[str, _Handover] = {}

    def expect(
        self,
        job_id: str,
        *,
        job_step_id: str,
        assignment_revision: int,
        pinky_id: str,
        omx_id: str,
    ) -> None:
        """현재 단계에서 완료를 기다릴 장비 pairing을 등록한다."""

        if not all((job_id, job_step_id, pinky_id, omx_id)):
            raise ValueError("job, step, Pinky, and OMX IDs are required")
        if assignment_revision < 0:
            raise ValueError("assignment revision cannot be negative")
        self._handovers[job_id] = _Handover(
            job_step_id=job_step_id,
            assignment_revision=assignment_revision,
            pinky_id=pinky_id,
            omx_id=omx_id,
        )

    def record(self, event: CompletionEvent) -> GateDecision:
        """현재 pairing의 성공 이벤트를 반영하고 두 역할 완료 시 한 번 release한다."""

        handover = self._handovers.get(event.job_id)
        if handover is None:
            return GateDecision(False, reason_code="UNKNOWN_GATE")
        if event.event_id in handover.processed_event_ids:
            return GateDecision(False, duplicate=True, reason_code="DUPLICATE_EVENT")
        handover.processed_event_ids.add(event.event_id)

        if event.job_step_id != handover.job_step_id:
            return GateDecision(False, reason_code="UNEXPECTED_STEP")
        if event.assignment_revision != handover.assignment_revision:
            return GateDecision(False, reason_code="STALE_ASSIGNMENT")

        expected_actor = {
            ActorRole.PINKY: handover.pinky_id,
            ActorRole.OMX: handover.omx_id,
        }.get(event.actor_role)
        if expected_actor != event.actor_id:
            return GateDecision(False, reason_code="UNEXPECTED_ACTOR")
        if not event.success:
            return GateDecision(False, reason_code="EXECUTION_FAILED")
        if handover.released:
            return GateDecision(False, reason_code="ALREADY_RELEASED")

        handover.completed_roles.add(event.actor_role)
        should_release = handover.completed_roles == {
            ActorRole.PINKY,
            ActorRole.OMX,
        }
        if should_release:
            handover.released = True
        return GateDecision(
            accepted=True,
            released=should_release,
            reason_code="GATE_RELEASED" if should_release else "WAITING_FOR_PEER",
        )

    def reassign_pinky(
        self,
        job_id: str,
        *,
        assignment_revision: int,
        pinky_id: str,
    ) -> None:
        """Pinky 재배정 시 과거 완료와 dedupe 범위를 모두 폐기한다."""

        handover = self._handover(job_id)
        if not pinky_id:
            raise ValueError("Pinky ID is required")
        if assignment_revision <= handover.assignment_revision:
            raise ValueError("reassignment revision must increase")
        self._handovers[job_id] = _Handover(
            job_step_id=handover.job_step_id,
            assignment_revision=assignment_revision,
            pinky_id=pinky_id,
            omx_id=handover.omx_id,
        )

    def cancel(self, job_id: str) -> None:
        """취소된 작업의 Gate 권한을 제거한다."""

        self._handovers.pop(job_id, None)

    def _handover(self, job_id: str) -> _Handover:
        try:
            return self._handovers[job_id]
        except KeyError as error:
            raise ValueError(f"unknown handover job {job_id}") from error
