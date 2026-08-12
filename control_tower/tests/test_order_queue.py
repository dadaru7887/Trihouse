"""SR41 긴급·FEFO 비선점 제출 queue 테스트."""

import pytest

from control_tower.fleet_manager.order_queue import (
    QueuedOrder,
    reorder_unsubmitted,
)


def test_urgent_reorders_only_unsubmitted_work() -> None:
    """긴급 접수 때문에 이미 사용 중인 Pinky 예약이 움직이는 회귀를 막는다."""
    active = QueuedOrder(1, "normal", False, None, 100, "in_use")
    normal = QueuedOrder(2, "normal", False, None, 200, "queued")
    urgent = QueuedOrder(3, "critical", True, 900, 300, "queued")

    result = reorder_unsubmitted((active, normal, urgent))

    assert [order.job_id for order in result] == [1, 3, 2]


def test_in_use_position_is_preserved_between_queued_slots() -> None:
    """정렬 구현이 중간의 실행 중 작업까지 앞뒤로 옮기는 회귀를 막는다."""
    normal = QueuedOrder(10, "normal", False, None, 100, "queued")
    active = QueuedOrder(11, "normal", False, None, 110, "in_use")
    urgent = QueuedOrder(12, "critical", True, 500, 120, "queued")

    result = reorder_unsubmitted((normal, active, urgent))

    assert [order.job_id for order in result] == [12, 11, 10]


def test_urgent_orders_use_fefo_then_request_time_then_job_id() -> None:
    """긴급 동률 순서가 실행마다 바뀌는 회귀를 막는다."""
    orders = (
        QueuedOrder(4, "critical", True, 900, 300, "queued"),
        QueuedOrder(3, "critical", True, 800, 400, "queued"),
        QueuedOrder(2, "critical", True, 800, 200, "queued"),
        QueuedOrder(1, "critical", True, 800, 200, "queued"),
    )

    assert [order.job_id for order in reorder_unsubmitted(orders)] == [
        1,
        2,
        3,
        4,
    ]


def test_expiry_nulls_are_sorted_after_known_expiry() -> None:
    """만료일 없는 주문이 FEFO 주문을 앞서는 회귀를 막는다."""
    no_expiry = QueuedOrder(1, "critical", True, None, 100, "queued")
    expires = QueuedOrder(2, "critical", True, 10_000, 200, "queued")

    assert [
        order.job_id
        for order in reorder_unsubmitted((no_expiry, expires))
    ] == [2, 1]


@pytest.mark.parametrize(
    ("priority", "urgent"),
    [("normal", True), ("critical", False)],
)
def test_urgent_flag_and_priority_must_match(
    priority: str, urgent: bool
) -> None:
    """jobs.context.urgent와 jobs.priority가 불일치한 요청을 막는다."""
    with pytest.raises(ValueError, match="urgent"):
        QueuedOrder(5, priority, urgent, None, 500, "queued")


def test_only_queued_and_in_use_states_are_accepted() -> None:
    """이미 RMF 제출된 상태를 새 queue가 임의 재정렬하는 회귀를 막는다."""
    with pytest.raises(ValueError, match="reservation_state"):
        QueuedOrder(6, "normal", False, None, 600, "reserved")


def test_low_priority_order_stays_after_normal_order() -> None:
    """DB가 허용하는 low 주문을 worker가 처리 불가로 만드는 회귀를 막는다."""
    low = QueuedOrder(7, "low", False, None, 100, "queued")
    normal = QueuedOrder(8, "normal", False, None, 200, "queued")

    assert [
        order.job_id for order in reorder_unsubmitted((low, normal))
    ] == [8, 7]
