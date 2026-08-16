"""vision worker가 Gateway 프로토콜 계약을 지키는지 검증한다."""

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vision_edge.perception import ArucoObservation, QrObservation  # noqa: E402
from vision_edge.worker import (  # noqa: E402
    VisionEdgeWorker,
    VisionRequest,
    VisionRequestError,
)


CAMERAS_CONFIG = Path(__file__).resolve().parents[2] / "config" / "cameras.simulation.yaml"

QR = QrObservation(value="SKU-MILK", bounding_box=((0.0, 0.0), (1.0, 1.0)))
MARKER = ArucoObservation(
    marker_id=1,
    dictionary="DICT_5X5_50",
    corners=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
    rvec=(0.0, 0.0, 0.0),
    tvec=(0.0, 0.0, 1.0),
)


def _request(**overrides) -> VisionRequest:
    payload = {
        "command_uuid": "cmd-1",
        "camera_id": "CAM-OMX-01-WRIST",
        "camera_role": "omx_wrist",
        "assignment_revision": 5,
        "observed_at_ms": 1_786_500_000_000,
        "purpose": "pick_pose",
        "expected_qr": "SKU-MILK",
        "expected_marker": 1,
    }
    payload.update(overrides)
    return VisionRequest(**payload)


@pytest.fixture
def worker() -> VisionEdgeWorker:
    return VisionEdgeWorker()


def test_response_carries_the_full_gateway_context(worker: VisionEdgeWorker) -> None:
    response = worker.handle(_request(), qr=QR, markers=(MARKER,))

    assert response.command_uuid == "cmd-1"
    assert response.camera_id == "CAM-OMX-01-WRIST"
    assert response.assignment_revision == 5
    assert response.observed_at_ms == 1_786_500_000_000
    assert response.dictionary == "DICT_5X5_50"
    assert response.accepted is True
    assert response.qr is QR
    assert response.markers == (MARKER,)


def test_marker_mismatch_is_reported_not_silently_accepted(
    worker: VisionEdgeWorker,
) -> None:
    other = ArucoObservation(
        marker_id=0,
        dictionary="DICT_5X5_50",
        corners=MARKER.corners,
        rvec=MARKER.rvec,
        tvec=MARKER.tvec,
    )

    response = worker.handle(_request(), qr=QR, markers=(other,))

    assert response.accepted is False
    assert response.reason_code == "MARKER_MISMATCH"


def test_incomplete_request_is_rejected() -> None:
    for override in (
        {"command_uuid": " "},
        {"camera_id": ""},
        {"assignment_revision": 0},
        {"observed_at_ms": 0},
        {"purpose": "surveillance"},
    ):
        with pytest.raises(VisionRequestError):
            _request(**override)


def test_pinky_video_is_never_accepted_as_omx_load_evidence(
    worker: VisionEdgeWorker,
) -> None:
    with pytest.raises(VisionRequestError, match="CAMERA_ROLE_NOT_LOAD_EVIDENCE"):
        worker.handle(
            _request(
                camera_id="CAM-PK-01",
                camera_role="pinky_travel",
                purpose="load_evidence",
            ),
            qr=QR,
            markers=(MARKER,),
            load_observation={
                "gripper_opened_over_roi": True,
                "item_inside_roi_after_release": True,
                "empty_gripper_retreated": True,
            },
        )


def test_pinky_camera_is_accepted_for_final_corridor_alignment(
    worker: VisionEdgeWorker,
) -> None:
    response = worker.handle(
        _request(
            camera_id="CAM-PK-01", camera_role="pinky_travel", purpose="alignment"
        ),
        qr=QR,
        markers=(MARKER,),
    )

    assert response.accepted is True
    assert response.load_evidence is None


def test_load_evidence_requires_wrist_and_roi_observations(
    worker: VisionEdgeWorker,
) -> None:
    with pytest.raises(VisionRequestError, match="wrist and basket ROI"):
        worker.handle(_request(purpose="load_evidence"), qr=QR, markers=(MARKER,))


def test_load_evidence_response_carries_the_outcome_and_refs(
    worker: VisionEdgeWorker,
) -> None:
    response = worker.handle(
        _request(purpose="load_evidence"),
        qr=QR,
        markers=(MARKER,),
        load_observation={
            "gripper_opened_over_roi": True,
            "item_inside_roi_after_release": True,
            "empty_gripper_retreated": True,
        },
        evidence_refs=("clip://omx-01/wrist/1",),
    )

    assert response.load_evidence.result == "LOAD_CONFIRMED"
    assert response.evidence_refs == ("clip://omx-01/wrist/1",)


def test_six_camera_fixtures_are_registered_without_invented_poses() -> None:
    text = CAMERAS_CONFIG.read_text(encoding="utf-8")
    camera_ids = [
        line.split(":", 1)[1].strip()
        for line in text.splitlines()
        if line.strip().startswith("- camera_id:")
    ]

    assert camera_ids == [
        "CAM-PK-01", "CAM-PK-02", "CAM-OMX-01-WRIST", "CAM-OMX-02-WRIST",
        "CAM-FIXED-01", "CAM-FIXED-02",
    ]
    # P1 캘리브레이션 전까지 map pose는 측정되지 않았다.
    assert text.count("map_pose: null") == 6
    assert "mediamtx_path: fixtures/" in text
