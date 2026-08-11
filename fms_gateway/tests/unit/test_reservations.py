
import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from fms_gateway.app.reservations import TimeWindow, find_earliest_slot


SEOUL = ZoneInfo("Asia/Seoul")


def seoul(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    return parsed.astimezone(SEOUL)


def test_moves_after_a_chain_of_conflicts():
    result = find_earliest_slot(
        seoul("2026-08-03T10:10:00+09:00"),
        seoul("2026-08-03T10:30:00+09:00"),
        [
            TimeWindow(
                seoul("2026-08-03T10:00:00+09:00"),
                seoul("2026-08-03T10:20:00+09:00"),
            ),
            TimeWindow(
                seoul("2026-08-03T10:25:00+09:00"),
                seoul("2026-08-03T10:40:00+09:00"),
            ),
        ],
    )

    assert result == TimeWindow(
        seoul("2026-08-03T10:40:00+09:00"),
        seoul("2026-08-03T11:00:00+09:00"),
    )


def test_touching_boundary_does_not_overlap():
    result = find_earliest_slot(
        seoul("2026-08-03T10:20:00+09:00"),
        seoul("2026-08-03T10:40:00+09:00"),
        [
            TimeWindow(
                seoul("2026-08-03T10:00:00+09:00"),
                seoul("2026-08-03T10:20:00+09:00"),
            )
        ],
    )

    assert result == TimeWindow(
        seoul("2026-08-03T10:20:00+09:00"),
        seoul("2026-08-03T10:40:00+09:00"),
    )


def test_unsorted_windows_still_choose_the_earliest_gap():
    result = find_earliest_slot(
        seoul("2026-08-03T09:50:00+09:00"),
        seoul("2026-08-03T10:00:00+09:00"),
        [
            TimeWindow(
                seoul("2026-08-03T10:20:00+09:00"),
                seoul("2026-08-03T10:30:00+09:00"),
            ),
            TimeWindow(
                seoul("2026-08-03T09:55:00+09:00"),
                seoul("2026-08-03T10:05:00+09:00"),
            ),
        ],
    )

    assert result == TimeWindow(
        seoul("2026-08-03T10:05:00+09:00"),
        seoul("2026-08-03T10:15:00+09:00"),
    )


def test_duration_is_preserved_after_shift():
    requested_start = seoul("2026-08-03T10:00:00+09:00")
    requested_end = seoul("2026-08-03T10:37:00+09:00")

    result = find_earliest_slot(
        requested_start,
        requested_end,
        [
            TimeWindow(
                seoul("2026-08-03T10:10:00+09:00"),
                seoul("2026-08-03T11:00:00+09:00"),
            )
        ],
    )

    assert result.end - result.start == dt.timedelta(minutes=37)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-08-03T10:00:00+09:00", "2026-08-03T10:00:00+09:00"),
        ("2026-08-03T10:01:00+09:00", "2026-08-03T10:00:00+09:00"),
    ],
)
def test_rejects_non_positive_duration(start, end):
    with pytest.raises(ValueError, match="end must be after start"):
        find_earliest_slot(seoul(start), seoul(end), [])


def test_rejects_naive_datetime():
    with pytest.raises(ValueError, match="Asia/Seoul-aware"):
        find_earliest_slot(
            dt.datetime(2026, 8, 3, 10, 0),
            dt.datetime(2026, 8, 3, 10, 10),
            [],
        )


def test_rejects_non_seoul_offset():
    with pytest.raises(ValueError, match="Asia/Seoul-aware"):
        find_earliest_slot(
            dt.datetime(2026, 8, 3, 1, 0, tzinfo=dt.UTC),
            dt.datetime(2026, 8, 3, 1, 10, tzinfo=dt.UTC),
            [],
        )
