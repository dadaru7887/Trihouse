"""Same-assignment zone readiness and item-level load evidence policy."""

from dataclasses import dataclass
from enum import StrEnum


class ReadinessRole(StrEnum):
    PINKY = "pinky"
    OMX = "omx"


LOAD_RESULTS = frozenset(
    {"LOAD_CONFIRMED", "DROP_DETECTED", "LOAD_UNCERTAIN", "GRASP_RETAINED"}
)


@dataclass(frozen=True)
class ReadinessFact:
    fact_id: str
    job_id: str
    handover_group_id: str
    assignment_revision: int
    role: ReadinessRole
    device_id: str
    dock_arrived: bool = False
    stationary: bool = False
    current_assignment: bool = False
    expected_item: bool = False
    safe_handover_pose: bool = False


@dataclass(frozen=True)
class HandoverDecision:
    accepted: bool
    released: bool = False
    reason_code: str = ""
    command: str | None = None


@dataclass(frozen=True)
class ItemLoadAttempt:
    attempt_id: str
    item_id: str
    result: str
    criteria: dict[str, object]
    observations: dict[str, object]
    metrics: dict[str, object]
    evidence_refs: tuple[str, ...]
    policy_name: str
    policy_version: str
    model_name: str
    model_version: str

    def validate(self) -> None:
        if self.result not in LOAD_RESULTS:
            raise ValueError("unsupported load result")
        required = (
            self.attempt_id,
            self.item_id,
            self.criteria,
            self.observations,
            self.metrics,
            self.evidence_refs,
            self.policy_name,
            self.policy_version,
            self.model_name,
            self.model_version,
        )
        if not all(required):
            raise ValueError("complete attempt record is required")


@dataclass(frozen=True)
class ItemLoadState:
    result: str
    pinky_departure_allowed: bool


class ZoneHandover:
    """Converge two readiness roles and persist fixture-observed load attempts."""

    def __init__(
        self,
        *,
        job_id: str,
        handover_group_id: str,
        assignment_revision: int,
        pinky_id: str,
        omx_id: str,
    ) -> None:
        if not all((job_id, handover_group_id, pinky_id, omx_id)):
            raise ValueError("complete handover assignment is required")
        if assignment_revision <= 0:
            raise ValueError("assignment revision must be positive")
        self.job_id = job_id
        self.handover_group_id = handover_group_id
        self.assignment_revision = assignment_revision
        self.pinky_id = pinky_id
        self.omx_id = omx_id
        self._fact_ids: set[str] = set()
        self._ready: set[ReadinessRole] = set()
        self._released = False
        self._attempts: list[ItemLoadAttempt] = []

    @property
    def attempts(self) -> tuple[ItemLoadAttempt, ...]:
        return tuple(self._attempts)

    def record(self, fact: ReadinessFact) -> HandoverDecision:
        if fact.job_id != self.job_id:
            return HandoverDecision(False, reason_code="CROSS_JOB_FACT")
        if fact.handover_group_id != self.handover_group_id:
            return HandoverDecision(False, reason_code="UNEXPECTED_GROUP")
        if fact.assignment_revision != self.assignment_revision:
            return HandoverDecision(False, reason_code="STALE_ASSIGNMENT")
        expected_device = (
            self.pinky_id if fact.role is ReadinessRole.PINKY else self.omx_id
        )
        if fact.device_id != expected_device:
            return HandoverDecision(False, reason_code="UNEXPECTED_DEVICE")
        if not fact.fact_id:
            return HandoverDecision(False, reason_code="INVALID_FACT")
        if fact.fact_id in self._fact_ids:
            return HandoverDecision(False, reason_code="DUPLICATE_FACT")
        self._fact_ids.add(fact.fact_id)
        if fact.role is ReadinessRole.PINKY and not (
            fact.dock_arrived and fact.stationary and fact.current_assignment
        ):
            return HandoverDecision(False, reason_code="PINKY_NOT_READY")
        if fact.role is ReadinessRole.OMX and not (
            fact.expected_item and fact.safe_handover_pose
        ):
            return HandoverDecision(False, reason_code="OMX_NOT_READY")
        if self._released:
            return HandoverDecision(False, reason_code="ALREADY_RELEASED")
        self._ready.add(fact.role)
        if self._ready == {ReadinessRole.PINKY, ReadinessRole.OMX}:
            self._released = True
            return HandoverDecision(
                True,
                released=True,
                reason_code="GATE_RELEASED",
                command="START_LOAD",
            )
        return HandoverDecision(True, reason_code="WAITING_FOR_PEER")

    def record_load_attempt(self, attempt: ItemLoadAttempt) -> ItemLoadState:
        attempt.validate()
        if any(existing.attempt_id == attempt.attempt_id for existing in self._attempts):
            raise ValueError("attempt ID must be unique")
        self._attempts.append(attempt)
        return ItemLoadState(
            result=attempt.result,
            pinky_departure_allowed=attempt.result == "LOAD_CONFIRMED",
        )
