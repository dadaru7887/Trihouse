"""Control Tower-owned immutable outbound resource assignment."""

from dataclasses import dataclass
from threading import RLock

from control_tower.fleet_manager.packing_station import (
    PackingDockCandidate,
    choose_packing_dock,
)


CHARGER_BY_MOBILE = {
    "PK_01": "TRIHOUSE-TEST-01-CHG-01",
    "PK_02": "TRIHOUSE-TEST-01-CHG-02",
}


class AssignmentConflict(Exception):
    """The requested revision would mutate an immutable assignment."""


class AssignmentUnavailable(Exception):
    """One or more exclusive resources cannot be reserved."""


@dataclass(frozen=True)
class DeviceCandidate:
    device_id: str
    available: bool

    def __post_init__(self) -> None:
        if not self.device_id:
            raise ValueError("device ID is required")


@dataclass(frozen=True)
class AssignmentRevision:
    job_id: str
    revision: int
    mobile_id: str
    omx_id: str
    packing_dock_code: str
    charger_code: str


@dataclass(frozen=True)
class RmfAcceptanceDecision:
    accepted: bool
    reason_code: str = ""


class ControlTowerAssigner:
    """Deterministically reserves complete assignments under one local lock.

    The Gateway persists the resulting revision with database constraints.  This
    pure policy lock makes concurrent in-process decisions follow the same rule.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._assignments: dict[str, AssignmentRevision] = {}
        self._reserved_mobile: dict[str, str] = {}
        self._reserved_omx: dict[str, str] = {}
        self._reserved_packing: dict[str, str] = {}

    def assign(
        self,
        job_id: str,
        *,
        revision: int,
        mobiles: tuple[DeviceCandidate, ...],
        arms: tuple[DeviceCandidate, ...],
        packing_docks: tuple[PackingDockCandidate, ...],
    ) -> AssignmentRevision:
        if not job_id or revision <= 0:
            raise ValueError("job ID and positive assignment revision are required")
        with self._lock:
            existing = self._assignments.get(job_id)
            if existing is not None:
                if existing.revision == revision:
                    return existing
                raise AssignmentConflict("use explicit reassignment for a new revision")
            return self._select_and_reserve(
                job_id, revision, mobiles, arms, packing_docks
            )

    def reassign(
        self,
        job_id: str,
        *,
        revision: int,
        mobiles: tuple[DeviceCandidate, ...],
        arms: tuple[DeviceCandidate, ...],
        packing_docks: tuple[PackingDockCandidate, ...],
    ) -> AssignmentRevision:
        with self._lock:
            existing = self._assignments.get(job_id)
            if existing is None:
                raise AssignmentConflict("job has no assignment to revise")
            if revision <= existing.revision:
                raise AssignmentConflict("reassignment revision must increase")
            self._release(existing)
            try:
                return self._select_and_reserve(
                    job_id, revision, mobiles, arms, packing_docks
                )
            except Exception:
                self._reserve(existing)
                self._assignments[job_id] = existing
                raise

    def validate_rmf_acceptance(
        self, job_id: str, *, revision: int, assigned_mobile_id: str
    ) -> RmfAcceptanceDecision:
        with self._lock:
            assignment = self._assignments.get(job_id)
            if assignment is None:
                return RmfAcceptanceDecision(False, "UNKNOWN_ASSIGNMENT")
            if assignment.revision != revision:
                return RmfAcceptanceDecision(False, "STALE_ASSIGNMENT")
            if assignment.mobile_id != assigned_mobile_id:
                return RmfAcceptanceDecision(False, "ASSIGNMENT_DEVICE_MISMATCH")
            return RmfAcceptanceDecision(True)

    def _select_and_reserve(
        self,
        job_id: str,
        revision: int,
        mobiles: tuple[DeviceCandidate, ...],
        arms: tuple[DeviceCandidate, ...],
        packing_docks: tuple[PackingDockCandidate, ...],
    ) -> AssignmentRevision:
        mobile = self._choose_device(mobiles, self._reserved_mobile)
        omx = self._choose_device(arms, self._reserved_omx)
        try:
            charger = CHARGER_BY_MOBILE[mobile]
        except KeyError as error:
            raise AssignmentUnavailable(f"mobile {mobile} has no fixed charger") from error
        try:
            packing = choose_packing_dock(
                packing_docks,
                reserved_codes=frozenset(self._reserved_packing),
            ).code
        except ValueError as error:
            raise AssignmentUnavailable(str(error)) from error
        assignment = AssignmentRevision(
            job_id=job_id,
            revision=revision,
            mobile_id=mobile,
            omx_id=omx,
            packing_dock_code=packing,
            charger_code=charger,
        )
        self._reserve(assignment)
        self._assignments[job_id] = assignment
        return assignment

    @staticmethod
    def _choose_device(
        candidates: tuple[DeviceCandidate, ...], reserved: dict[str, str]
    ) -> str:
        available = sorted(
            candidate.device_id
            for candidate in candidates
            if candidate.available and candidate.device_id not in reserved
        )
        if not available:
            raise AssignmentUnavailable("no device is available")
        return available[0]

    def _reserve(self, assignment: AssignmentRevision) -> None:
        self._reserved_mobile[assignment.mobile_id] = assignment.job_id
        self._reserved_omx[assignment.omx_id] = assignment.job_id
        self._reserved_packing[assignment.packing_dock_code] = assignment.job_id

    def _release(self, assignment: AssignmentRevision) -> None:
        self._reserved_mobile.pop(assignment.mobile_id, None)
        self._reserved_omx.pop(assignment.omx_id, None)
        self._reserved_packing.pop(assignment.packing_dock_code, None)


__all__ = [
    "AssignmentConflict",
    "AssignmentRevision",
    "AssignmentUnavailable",
    "CHARGER_BY_MOBILE",
    "ControlTowerAssigner",
    "DeviceCandidate",
    "PackingDockCandidate",
    "RmfAcceptanceDecision",
]
