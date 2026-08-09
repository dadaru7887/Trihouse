"""등록된 OMX 바구니 적재 pose에 제한된 2D 보정을 적용하는 정책."""
from __future__ import annotations

from dataclasses import dataclass
from math import cos, hypot, radians, sin


@dataclass(frozen=True)
class Pose2D:
    x: float
    y: float
    yaw_deg: float


@dataclass(frozen=True)
class BasketObservation:
    corners: tuple[tuple[float, float], ...]
    translation_m: tuple[float, float]
    rotation_deg: float


@dataclass(frozen=True)
class BasketCorrectionResult:
    approved: bool
    action: str
    corrected_pose: Pose2D | None = None


class BasketCorrectionPolicy:
    def __init__(self, *, max_translation_m: float, max_rotation_deg: float) -> None:
        if max_translation_m < 0 or max_rotation_deg < 0:
            raise ValueError('basket correction limits must be non-negative')
        self._max_translation_m = max_translation_m
        self._max_rotation_deg = max_rotation_deg

    def correct(self, registered_pose: Pose2D, observed: BasketObservation | None) -> BasketCorrectionResult:
        if observed is None or len(observed.corners) != 4 or len(set(observed.corners)) != 4:
            return BasketCorrectionResult(False, 'REQUEST_PINKY_REPOSITION')
        dx, dy = observed.translation_m
        if hypot(dx, dy) > self._max_translation_m or abs(observed.rotation_deg) > self._max_rotation_deg:
            return BasketCorrectionResult(False, 'REQUEST_PINKY_REPOSITION')
        theta = radians(observed.rotation_deg)
        corrected = Pose2D(
            x=cos(theta) * registered_pose.x - sin(theta) * registered_pose.y + dx,
            y=sin(theta) * registered_pose.x + cos(theta) * registered_pose.y + dy,
            yaw_deg=registered_pose.yaw_deg + observed.rotation_deg,
        )
        return BasketCorrectionResult(True, 'LOAD_WITH_CORRECTION', corrected)
