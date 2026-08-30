"""OpenCV QR/ArUco 처리와 시각 적재 증거 판정.

이 모듈은 OMX 장비 ROS 안이 아니라 4060 서버용 독립 worker에서 돈다.
QR은 `cv2.QRCodeDetector`, 마커는 `cv2.aruco.DICT_5X5_50`으로만 읽으며
현장에서 확정된 실제 마커 ID(0/1/2)만 취급한다. 합성 ID를 만들지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


ARUCO_DICTIONARY = "DICT_5X5_50"


@dataclass(frozen=True)
class QrObservation:
    value: str
    bounding_box: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class ArucoObservation:
    marker_id: int
    dictionary: str
    corners: tuple[tuple[float, float], ...]
    rvec: tuple[float, float, float]
    tvec: tuple[float, float, float]


@dataclass(frozen=True)
class MarkerVerification:
    accepted: bool
    reason_code: str = ""


@dataclass(frozen=True)
class LoadEvidence:
    """정확히 네 가지 결과 중 하나와 그 근거 참조."""

    result: str
    reason_code: str
    evidence_refs: tuple[str, ...]


class VisionPerception:
    """OpenCV 검출기를 감싸 결정적인 관측 자료형으로 바꾼다."""

    def __init__(self, *, detector: Any | None = None, aruco: Any | None = None) -> None:
        self._detector = detector
        self._aruco = aruco

    # --- 검증 ---------------------------------------------------------------

    def verify(
        self,
        *,
        qr: str | None,
        marker_id: int | None,
        expected_qr: str,
        expected_marker: int,
    ) -> MarkerVerification:
        """QR과 ArUco가 **둘 다** 기대값과 같아야 통과한다."""
        if qr is None or marker_id is None:
            return MarkerVerification(False, "OBSERVATION_MISSING")
        if qr != expected_qr:
            return MarkerVerification(False, "QR_MISMATCH")
        if marker_id != expected_marker:
            return MarkerVerification(False, "MARKER_MISMATCH")
        return MarkerVerification(True)

    # --- 검출 ---------------------------------------------------------------

    def detect_qr(self, image: Any) -> QrObservation | None:
        detector = self._detector or _qr_detector()
        value, points, _ = detector.detectAndDecode(image)
        if not value or points is None or len(points) == 0:
            return None
        return QrObservation(
            value=str(value),
            bounding_box=tuple(
                (float(point[0]), float(point[1])) for point in _flatten(points)
            ),
        )

    def detect_markers(
        self,
        image: Any,
        *,
        camera_matrix: Any = None,
        distortion: Any = None,
        marker_length_m: float = 0.05,
    ) -> tuple[ArucoObservation, ...]:
        aruco = self._aruco or _aruco_module()
        corners, ids, _ = aruco.detect(image)
        if ids is None or len(ids) == 0:
            return ()
        poses = aruco.estimate_poses(
            corners,
            marker_length_m=marker_length_m,
            camera_matrix=camera_matrix,
            distortion=distortion,
        )
        observations: list[ArucoObservation] = []
        for index, marker_id in enumerate(_flatten_ids(ids)):
            rvec, tvec = poses[index]
            observations.append(
                ArucoObservation(
                    marker_id=int(marker_id),
                    dictionary=ARUCO_DICTIONARY,
                    corners=tuple(
                        (float(point[0]), float(point[1]))
                        for point in _flatten(corners[index])
                    ),
                    rvec=(float(rvec[0]), float(rvec[1]), float(rvec[2])),
                    tvec=(float(tvec[0]), float(tvec[1]), float(tvec[2])),
                )
            )
        return tuple(observations)


def classify_load_evidence(
    *,
    gripper_opened_over_roi: bool,
    item_inside_roi_after_release: bool,
    empty_gripper_retreated: bool,
    item_seen_outside_roi: bool = False,
    evidence_refs: Sequence[str] = (),
) -> LoadEvidence:
    """손목 전/후 추적과 고정 카메라 바구니 ROI 관측을 하나의 결과로 합친다.

    확인은 세 조건이 모두 참일 때만 한다. 그리퍼가 ROI 위에서 열렸고, 물건이
    ROI 안에 남아 있고, 빈 그리퍼가 안전하게 물러났을 때다.
    """
    refs = tuple(evidence_refs)
    if gripper_opened_over_roi and item_inside_roi_after_release and empty_gripper_retreated:
        return LoadEvidence("LOAD_CONFIRMED", "ALL_CRITERIA_MET", refs)
    if gripper_opened_over_roi and not item_inside_roi_after_release and item_seen_outside_roi:
        return LoadEvidence("DROP_DETECTED", "ITEM_LEFT_THE_BASKET", refs)
    if not empty_gripper_retreated:
        # 그리퍼가 여전히 물건을 쥐고 있으면 적재가 아니라 파지 유지다.
        return LoadEvidence("GRASP_RETAINED", "GRIPPER_STILL_HOLDS_ITEM", refs)
    return LoadEvidence("LOAD_UNCERTAIN", "EVIDENCE_INCONCLUSIVE", refs)


def _qr_detector() -> Any:
    import cv2

    return cv2.QRCodeDetector()


def _aruco_module() -> Any:
    raise RuntimeError(
        "An ArUco backend must be injected; P0 never guesses camera intrinsics."
    )


def _flatten(points: Any) -> Any:
    flattened = points
    while (
        hasattr(flattened, "__len__")
        and len(flattened) == 1
        and hasattr(flattened[0], "__len__")
        and len(flattened[0]) > 1
    ):
        flattened = flattened[0]
    return flattened


def _flatten_ids(ids: Any) -> list[int]:
    return [int(value[0]) if hasattr(value, "__len__") else int(value) for value in ids]


__all__ = [
    "ARUCO_DICTIONARY",
    "ArucoObservation",
    "LoadEvidence",
    "MarkerVerification",
    "QrObservation",
    "VisionPerception",
    "classify_load_evidence",
]
