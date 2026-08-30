"""OMX 파지·적재 준비 전에 QR 물품 ID와 ArUco pose를 확인하는 guard."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PickAuthorization:
    job_id: str
    order_id: str
    item_id: str
    shelf_id: str
    slot_id: str


@dataclass(frozen=True)
class QrObservation:
    item_id: str
    order_id: str


@dataclass(frozen=True)
class MarkerObservation:
    marker_id: str
    translation_error_m: float
    rotation_error_deg: float


@dataclass(frozen=True)
class ValidationResult:
    approved: bool
    reason: str = ''


class MarkerPolicy:
    def __init__(self, *, max_translation_error_m: float, max_rotation_error_deg: float) -> None:
        if max_translation_error_m < 0 or max_rotation_error_deg < 0:
            raise ValueError('marker tolerances must be non-negative')
        self._max_translation_error_m = max_translation_error_m
        self._max_rotation_error_deg = max_rotation_error_deg

    @staticmethod
    def verify_qr(expected: PickAuthorization, observed: QrObservation | None) -> ValidationResult:
        if observed is None:
            return ValidationResult(False, 'QR not recognized')
        if observed.item_id != expected.item_id:
            return ValidationResult(False, 'item mismatch')
        if observed.order_id != expected.order_id:
            return ValidationResult(False, 'order mismatch')
        return ValidationResult(True)

    def verify_marker(self, expected: PickAuthorization, observed: MarkerObservation | None) -> ValidationResult:
        if observed is None:
            return ValidationResult(False, 'marker not recognized')
        if observed.marker_id != expected.shelf_id:
            return ValidationResult(False, 'marker mismatch')
        if observed.translation_error_m > self._max_translation_error_m:
            return ValidationResult(False, 'translation tolerance exceeded')
        if observed.rotation_error_deg > self._max_rotation_error_deg:
            return ValidationResult(False, 'rotation tolerance exceeded')
        return ValidationResult(True)
