"""4060 서버에서 도는 독립 vision worker.

OpenCV QR/ArUco 처리는 OMX 장비 ROS 안이 아니라 여기에서만 돈다. Pinky
fixture는 마커 인식 pose로 최종 통로/Dock 정렬을 하고, OMX fixture는 같은
실제 마커 ID로 픽 pose를 보정한다. 합성 마커 ID는 만들지 않는다.
"""

from .perception import (  # noqa: F401
    ARUCO_DICTIONARY,
    ArucoObservation,
    LoadEvidence,
    MarkerVerification,
    QrObservation,
    VisionPerception,
    classify_load_evidence,
)
from .worker import VisionEdgeWorker, VisionRequest, VisionResponse  # noqa: F401

__all__ = [
    "ARUCO_DICTIONARY",
    "ArucoObservation",
    "LoadEvidence",
    "MarkerVerification",
    "QrObservation",
    "VisionEdgeWorker",
    "VisionPerception",
    "VisionRequest",
    "VisionResponse",
    "classify_load_evidence",
]
