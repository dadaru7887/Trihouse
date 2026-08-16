"""여러 자원 스케줄러가 공유하는 예약 시간 구간 규칙."""


from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable


SEOUL_OFFSET = timedelta(hours=9)


def _require_seoul_time(value: datetime) -> None:
    """서버/호스트 시간대와 무관하게 모든 예약을 +09:00으로 통일한다."""
    if value.tzinfo is None or value.utcoffset() != SEOUL_OFFSET:
        raise ValueError("datetime must be Asia/Seoul-aware (+09:00)")


@dataclass(frozen=True, order=True)
class TimeWindow:
    """종료 시각은 점유하지 않는 반개구간: ``start <= time < end``."""

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
    """겹치는 모든 예약 뒤로 이동한 가장 빠른 요청 길이의 구간을 반환한다.

    요청 길이는 보존된다. 반개구간끼리는 끝과 시작이 같아도 겹치지 않으므로
    한 예약이 끝나는 즉시 다음 예약이 시작할 수 있다.
    """

    requested = TimeWindow(requested_start, requested_end)
    duration = requested.end - requested.start
    candidate = requested

    # 시작 시각 순으로 훑으면 매 충돌마다 후보를 기존 예약의 끝으로 밀 수 있다.
    for existing in sorted(occupied):
        if candidate.end <= existing.start:
            break
        if candidate.start >= existing.end:
            continue
        candidate = TimeWindow(existing.end, existing.end + duration)

    return candidate
