"""Pinky SR이 정한 사람 위험·비상 표시 우선순위 정책."""
from enum import IntEnum


class Indicator(IntEnum):
    OFF = 0
    PERSON_DETECTED = 1
    EMERGENCY = 2


def select_indicator(*, person_detected: bool, emergency: bool, handover_waiting: bool) -> Indicator:
    """Handover state is reported to FMS/LCD, never confused with a hazard LED."""
    if emergency:
        return Indicator.EMERGENCY
    if person_detected:
        return Indicator.PERSON_DETECTED
    return Indicator.OFF
