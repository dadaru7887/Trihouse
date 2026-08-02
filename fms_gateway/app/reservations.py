"""Reservation time-window rules shared by resource schedulers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable


SEOUL_OFFSET = timedelta(hours=9)


def _require_seoul_time(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != SEOUL_OFFSET:
        raise ValueError("datetime must be Asia/Seoul-aware (+09:00)")


@dataclass(frozen=True, order=True)
class TimeWindow:
    """A half-open reservation interval: ``start <= time < end``."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        _require_seoul_time(self.start)
        _require_seoul_time(self.end)
        if self.end <= self.start:
            raise ValueError("end must be after start")


def find_earliest_slot(
    requested_start: datetime,
    requested_end: datetime,
    occupied: Iterable[TimeWindow],
) -> TimeWindow:
    """Return the requested slot, shifted after every overlapping reservation.

    The requested duration is preserved. Adjacent half-open windows do not
    overlap, so one reservation may start exactly when the previous one ends.
    """

    requested = TimeWindow(requested_start, requested_end)
    duration = requested.end - requested.start
    candidate = requested

    for existing in sorted(occupied):
        if candidate.end <= existing.start:
            break
        if candidate.start >= existing.end:
            continue
        candidate = TimeWindow(existing.end, existing.end + duration)

    return candidate
