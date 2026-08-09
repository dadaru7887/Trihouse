"""입고·출고가 공유하는 주문 단계, NDJSON envelope, 통신 복구 계약.

이 모듈은 Control Tower 도메인 계층이다. ROS topic, DB, OMX 장비를 직접 호출하지
않고 gateway/adapter가 검증한 사실(event)만 받아 상태를 바꾼다. 따라서 Gazebo mock과
실기 adapter가 같은 순서·중복 제거·비상 복구 규칙을 재사용할 수 있다.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProtocolError(ValueError):
    """관제↔장비 전송 envelope가 공통 계약을 만족하지 않을 때 발생한다."""


@dataclass(frozen=True)
class ProtocolEnvelope:
    """모든 작업 명령·결과가 반드시 갖는 전송 식별자 묶음이다."""

    schema_version: str
    message_id: str
    type: str
    sent_at: str
    robot_id: str
    job_id: str
    order_id: str
    job_step_id: str

    @classmethod
    def create(cls, **values: str) -> "ProtocolEnvelope":
        """빈 필드를 허용하지 않아 재전송·감사·장비 결과 대조의 기준을 보장한다."""
        required = (
            "schema_version", "message_id", "type", "sent_at", "robot_id",
            "job_id", "order_id", "job_step_id",
        )
        missing = [field for field in required if not str(values.get(field, "")).strip()]
        if missing:
            raise ProtocolError(f"missing envelope fields: {', '.join(missing)}")
        return cls(**{field: str(values[field]) for field in required})


class JobPhase(str, Enum):
    """입고·출고 공통 주문 생명주기와 사람이 판단해야 하는 분기를 표현한다."""

    PENDING = "PENDING"
    RESERVED = "RESERVED"
    PICKING = "PICKING"
    PINKY_TO_STATION = "PINKY_TO_STATION"
    HANDOVER_READY = "HANDOVER_READY"
    LOADING = "LOADING"
    LOADED = "LOADED"
    DELIVERING = "DELIVERING"
    UNLOADING = "UNLOADING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    HELD = "HELD"
    EMERGENCY = "EMERGENCY"
    RECOVERY = "RECOVERY"
    REASSIGNED = "REASSIGNED"


class JobEvent(str, Enum):
    """실제 adapter가 보고하는 완료 사실만 상태 전이에 사용한다."""

    RESERVE = "RESERVE"
    OMX_PICKED = "OMX_PICKED"
    PINKY_AT_STATION = "PINKY_AT_STATION"
    HANDOVER_READY = "HANDOVER_READY"
    OMX_LOAD_SUCCEEDED = "OMX_LOAD_SUCCEEDED"
    PINKY_DEPARTED = "PINKY_DEPARTED"
    PINKY_AT_DESTINATION = "PINKY_AT_DESTINATION"
    OMX_UNLOAD_SUCCEEDED = "OMX_UNLOAD_SUCCEEDED"
    FAIL = "FAIL"
    HOLD = "HOLD"
    EMERGENCY = "EMERGENCY"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    REASSIGN = "REASSIGN"


@dataclass(frozen=True)
class TransitionResult:
    """gateway가 ACK와 audit event에 그대로 사용할 전이 결과다."""

    accepted: bool
    duplicate: bool
    phase: JobPhase
    detail: str


class JobStateMachine:
    """물리 확인 없는 OMX 성공 응답만으로 다음 단계로 가지 않게 하는 상태기계다."""

    _NORMAL_TRANSITIONS = {
        (JobPhase.PENDING, JobEvent.RESERVE): JobPhase.RESERVED,
        (JobPhase.RESERVED, JobEvent.OMX_PICKED): JobPhase.PICKING,
        (JobPhase.PICKING, JobEvent.PINKY_AT_STATION): JobPhase.PINKY_TO_STATION,
        (JobPhase.PINKY_TO_STATION, JobEvent.HANDOVER_READY): JobPhase.HANDOVER_READY,
        (JobPhase.HANDOVER_READY, JobEvent.OMX_LOAD_SUCCEEDED): JobPhase.LOADED,
        (JobPhase.LOADED, JobEvent.PINKY_DEPARTED): JobPhase.DELIVERING,
        (JobPhase.DELIVERING, JobEvent.PINKY_AT_DESTINATION): JobPhase.UNLOADING,
        (JobPhase.UNLOADING, JobEvent.OMX_UNLOAD_SUCCEEDED): JobPhase.COMPLETED,
        (JobPhase.HELD, JobEvent.REASSIGN): JobPhase.REASSIGNED,
    }

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.phase = JobPhase.PENDING
        self._seen_message_ids: set[str] = set()

    def apply(self, envelope: ProtocolEnvelope, event: JobEvent, *, cargo_confirmed: bool = False) -> TransitionResult:
        """한 번 처리한 message_id는 상태를 다시 바꾸지 않고 멱등 ACK만 돌려준다."""
        if envelope.job_id != self.job_id:
            return TransitionResult(False, False, self.phase, "job_id does not match state machine")
        if envelope.message_id in self._seen_message_ids:
            return TransitionResult(True, True, self.phase, "duplicate message ignored")
        self._seen_message_ids.add(envelope.message_id)

        # 비상/보류/실패는 어느 운반 단계에서도 안전하게 우선 적용한다.
        if event is JobEvent.EMERGENCY:
            self.phase = JobPhase.EMERGENCY
            return TransitionResult(True, False, self.phase, "emergency latched; automatic resume is forbidden")
        if event is JobEvent.HOLD:
            self.phase = JobPhase.HELD
            return TransitionResult(True, False, self.phase, "job held for operator decision")
        if event is JobEvent.FAIL:
            self.phase = JobPhase.FAILED
            return TransitionResult(True, False, self.phase, "job failed")
        if self.phase is JobPhase.EMERGENCY:
            if event is JobEvent.RECOVERY_REQUIRED:
                self.phase = JobPhase.RECOVERY
                return TransitionResult(True, False, self.phase, "recovery inspection required")
            return TransitionResult(False, False, self.phase, "emergency requires explicit recovery decision")

        # 적재/하차 모두 OMX 완료와 cargo lock/load-cell 등 물리 확인이 함께 있어야 한다.
        if event in (JobEvent.OMX_LOAD_SUCCEEDED, JobEvent.OMX_UNLOAD_SUCCEEDED) and not cargo_confirmed:
            return TransitionResult(False, False, self.phase, "physical cargo confirmation is required")
        target = self._NORMAL_TRANSITIONS.get((self.phase, event))
        if target is None:
            return TransitionResult(False, False, self.phase, f"event {event.value} is invalid from {self.phase.value}")
        self.phase = target
        return TransitionResult(True, False, self.phase, f"transitioned by {event.value}")


class LinkReconciler:
    """통신 단절 뒤 마지막 체크포인트가 일치할 때만 관제 지시를 다시 받게 한다."""

    def __init__(self) -> None:
        self.connected = True
        self._checkpoint: tuple[str, JobPhase, str] | None = None

    def accept_new_work(self) -> bool:
        """단절 중에는 새 작업을 배정하지 않는 fail-closed 경계다."""
        return self.connected

    def disconnect(self, *, job_id: str, phase: JobPhase, checkpoint: str) -> None:
        """Pinky/OMX가 보존한 마지막 합의 단계만 재연결 대조에 사용한다."""
        self.connected = False
        self._checkpoint = (job_id, phase, checkpoint)

    def reconnect(self, *, job_id: str, phase: JobPhase, checkpoint: str) -> bool:
        """관제의 job·phase·checkpoint가 모두 같아야 link를 다시 열어준다."""
        if self._checkpoint != (job_id, phase, checkpoint):
            return False
        self.connected = True
        return True
