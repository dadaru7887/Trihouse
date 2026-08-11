"""fleet action server가 쓰는 Pinky 운반·인계·복귀의 순수 상태 machine."""

from dataclasses import dataclass
from enum import Enum


class JobPhase(str, Enum):
    IDLE = "IDLE"
    REJECTED = "REJECTED"
    NAVIGATING = "NAVIGATING"
    WAITING_HANDOVER = "WAITING_HANDOVER"
    EMERGENCY = "EMERGENCY"
    RETURNING = "RETURNING"
    HEALTH_CHECK = "HEALTH_CHECK"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class JobCommand:
    command_id: str
    job_id: str
    map_revision: str
    destination_kind: str
    requires_cargo: bool = True


@dataclass(frozen=True)
class WorkflowResult:
    accepted: bool
    duplicate: bool
    phase: JobPhase
    detail: str
    return_location_id: str = ""


class TransportWorkflow:
    """Enforces Pinky's boundary: FMS approves work, Pinky moves and waits."""
    def __init__(self, *, robot_id: str, expected_map_revision: str) -> None:
        self.robot_id = robot_id
        self.expected_map_revision = expected_map_revision
        self.phase = JobPhase.IDLE
        self.command_id = ""
        self.job_id = ""
        self.destination_kind = ""
        self.recovery_return = False

    def accept(self, command: JobCommand, *, ready: bool, cargo_confirmed: bool) -> WorkflowResult:
        if command.command_id == self.command_id:
            return WorkflowResult(True, True, self.phase, "duplicate command")
        if self.phase is JobPhase.RETURNING and not command.requires_cargo:
            self.command_id, self.job_id = command.command_id, command.job_id
            self.destination_kind, self.recovery_return, self.phase = command.destination_kind, True, JobPhase.NAVIGATING
            return WorkflowResult(True, False, self.phase, "recovery return accepted")
        if self.phase is not JobPhase.IDLE:
            return WorkflowResult(False, False, JobPhase.REJECTED, "robot is not idle")
        if not ready:
            return WorkflowResult(False, False, JobPhase.REJECTED, "robot is not ready")
        if command.requires_cargo and not cargo_confirmed:
            return WorkflowResult(False, False, JobPhase.REJECTED, "cargo handover is not confirmed")
        if command.map_revision != self.expected_map_revision:
            return WorkflowResult(False, False, JobPhase.REJECTED, "map revision mismatch")
        self.command_id, self.job_id, self.phase = command.command_id, command.job_id, JobPhase.NAVIGATING
        self.destination_kind = command.destination_kind
        return WorkflowResult(True, False, self.phase, "navigation accepted")

    def nav_result(self, *, succeeded: bool, stationary: bool) -> WorkflowResult:
        if self.phase is not JobPhase.NAVIGATING:
            return WorkflowResult(False, False, self.phase, "no active navigation")
        if not succeeded:
            self.phase = JobPhase.IDLE
            return WorkflowResult(False, False, self.phase, "navigation failed")
        if not stationary:
            return WorkflowResult(True, False, self.phase, "waiting for stop")
        if self.destination_kind.startswith('RETURN_'):
            self.command_id = ""
            self.job_id = ""
            self.phase = JobPhase.HEALTH_CHECK if self.recovery_return else JobPhase.IDLE
            return WorkflowResult(True, False, self.phase, "return destination reached")
        self.phase = JobPhase.WAITING_HANDOVER
        return WorkflowResult(True, False, self.phase, "arrived and stationary")

    def reassign(self, command_id: str, map_revision: str) -> WorkflowResult:
        """FMS can redirect a waiting delivery without replacing its cargo/job."""
        if self.phase is not JobPhase.WAITING_HANDOVER:
            return WorkflowResult(False, False, self.phase, "robot is not waiting for handover")
        if map_revision != self.expected_map_revision:
            return WorkflowResult(False, False, self.phase, "map revision mismatch")
        self.command_id = command_id
        self.phase = JobPhase.NAVIGATING
        return WorkflowResult(True, False, self.phase, "reassigned by FMS")

    def complete_handover(self) -> WorkflowResult:
        """Release only after the cargo controller has confirmed physical unlock."""
        if self.phase is not JobPhase.WAITING_HANDOVER:
            return WorkflowResult(False, False, self.phase, "robot is not waiting for handover")
        self.command_id = ""
        self.job_id = ""
        self.phase = JobPhase.IDLE
        return WorkflowResult(True, False, self.phase, "handover confirmed")

    def enter_emergency(self, detail: str) -> WorkflowResult:
        self.phase = JobPhase.EMERGENCY
        return WorkflowResult(False, False, self.phase, detail)

    def clear_emergency(self, *, return_location_id: str) -> WorkflowResult:
        if self.phase is not JobPhase.EMERGENCY:
            return WorkflowResult(False, False, self.phase, "no emergency is active")
        self.phase = JobPhase.RETURNING
        return WorkflowResult(True, False, self.phase, "return for inspection", return_location_id)

    def finish_return(self, *, health_ok: bool, cargo_present: bool) -> WorkflowResult:
        if self.phase not in (JobPhase.RETURNING, JobPhase.HEALTH_CHECK):
            return WorkflowResult(False, False, self.phase, "return was not requested")
        self.command_id = ""
        self.job_id = ""
        self.recovery_return = False
        self.phase = JobPhase.IDLE if health_ok and not cargo_present else JobPhase.UNAVAILABLE
        return WorkflowResult(self.phase is JobPhase.IDLE, False, self.phase, "health check complete")
