"""Gateway 프로토콜로 관측을 돌려주는 독립 vision worker.

worker는 카메라 ID, assignment revision, command UUID, 타임스탬프를 그대로
싣고 QR/마커 관측과 적재 증거를 반환한다. Pinky 영상은 절대 OMX 적재
증거로 쓰지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .perception import (
    ARUCO_DICTIONARY,
    ArucoObservation,
    LoadEvidence,
    QrObservation,
    VisionPerception,
    classify_load_evidence,
)


class VisionRequestError(ValueError):
    """요청이 Gateway 프로토콜을 만족하지 못했다."""


# 카메라 역할별로 허용된 용도. Pinky 카메라는 이동 감시용이며 적재 증거가
# 될 수 없다.
LOAD_EVIDENCE_ROLES = frozenset({"omx_wrist", "warehouse_fixed"})
ALIGNMENT_ROLES = frozenset({"pinky_travel", "warehouse_fixed"})


@dataclass(frozen=True)
class VisionRequest:
    command_uuid: str
    camera_id: str
    camera_role: str
    assignment_revision: int
    observed_at_ms: int
    purpose: str
    expected_qr: str = ""
    expected_marker: int = -1

    def __post_init__(self) -> None:
        if not self.command_uuid.strip():
            raise VisionRequestError("command_uuid is required")
        if not self.camera_id.strip():
            raise VisionRequestError("camera_id is required")
        if self.assignment_revision <= 0:
            raise VisionRequestError("assignment_revision must be positive")
        if self.observed_at_ms <= 0:
            raise VisionRequestError("observed_at_ms must be positive")
        if self.purpose not in ("alignment", "pick_pose", "load_evidence"):
            raise VisionRequestError(f"unsupported purpose: {self.purpose}")


@dataclass(frozen=True)
class VisionResponse:
    command_uuid: str
    camera_id: str
    camera_role: str
    assignment_revision: int
    observed_at_ms: int
    dictionary: str = ARUCO_DICTIONARY
    qr: QrObservation | None = None
    markers: tuple[ArucoObservation, ...] = ()
    accepted: bool = False
    reason_code: str = ""
    load_evidence: LoadEvidence | None = None
    evidence_refs: tuple[str, ...] = field(default=())


class VisionEdgeWorker:
    """한 요청을 받아 결정적인 관측 응답 하나를 만든다."""

    def __init__(self, perception: VisionPerception | None = None) -> None:
        self._perception = perception or VisionPerception()

    def handle(
        self,
        request: VisionRequest,
        *,
        qr: QrObservation | None = None,
        markers: tuple[ArucoObservation, ...] = (),
        load_observation: Mapping[str, Any] | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> VisionResponse:
        self._check_role(request)

        marker_id = markers[0].marker_id if markers else None
        verification = self._perception.verify(
            qr=qr.value if qr is not None else None,
            marker_id=marker_id,
            expected_qr=request.expected_qr,
            expected_marker=request.expected_marker,
        )

        evidence: LoadEvidence | None = None
        if request.purpose == "load_evidence":
            if load_observation is None:
                raise VisionRequestError(
                    "load evidence requires wrist and basket ROI observations"
                )
            evidence = classify_load_evidence(
                gripper_opened_over_roi=bool(
                    load_observation["gripper_opened_over_roi"]
                ),
                item_inside_roi_after_release=bool(
                    load_observation["item_inside_roi_after_release"]
                ),
                empty_gripper_retreated=bool(
                    load_observation["empty_gripper_retreated"]
                ),
                item_seen_outside_roi=bool(
                    load_observation.get("item_seen_outside_roi", False)
                ),
                evidence_refs=evidence_refs,
            )

        return VisionResponse(
            command_uuid=request.command_uuid,
            camera_id=request.camera_id,
            camera_role=request.camera_role,
            assignment_revision=request.assignment_revision,
            observed_at_ms=request.observed_at_ms,
            qr=qr,
            markers=markers,
            accepted=verification.accepted,
            reason_code=verification.reason_code,
            load_evidence=evidence,
            evidence_refs=evidence_refs,
        )

    @staticmethod
    def _check_role(request: VisionRequest) -> None:
        if request.purpose == "load_evidence":
            if request.camera_role not in LOAD_EVIDENCE_ROLES:
                raise VisionRequestError(
                    f"CAMERA_ROLE_NOT_LOAD_EVIDENCE: {request.camera_role}"
                )
        elif request.purpose == "alignment":
            if request.camera_role not in ALIGNMENT_ROLES:
                raise VisionRequestError(
                    f"CAMERA_ROLE_NOT_ALIGNMENT: {request.camera_role}"
                )


__all__ = [
    "ALIGNMENT_ROLES",
    "LOAD_EVIDENCE_ROLES",
    "VisionEdgeWorker",
    "VisionRequest",
    "VisionRequestError",
    "VisionResponse",
]
