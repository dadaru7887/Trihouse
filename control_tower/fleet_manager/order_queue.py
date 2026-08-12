"""SR41 긴급 주문을 실행 중 작업 뒤에서 결정적으로 정렬한다."""

from dataclasses import dataclass


_PRIORITY_RANK = {"critical": 0, "high": 1, "normal": 2, "low": 3}
_MAX_MILLIS = 2**63 - 1


@dataclass(frozen=True)
class QueuedOrder:
    job_id: int
    priority: str
    context_urgent: bool
    earliest_item_expiry_ms: int | None
    created_at_ms: int
    reservation_state: str

    def __post_init__(self) -> None:
        if self.job_id <= 0:
            raise ValueError("job_id must be positive")
        if self.priority not in _PRIORITY_RANK:
            raise ValueError("unsupported priority")
        if (self.priority == "critical") != self.context_urgent:
            raise ValueError("urgent flag and critical priority must match")
        if self.earliest_item_expiry_ms is not None:
            if self.earliest_item_expiry_ms < 0:
                raise ValueError("earliest expiry cannot be negative")
        if self.created_at_ms < 0:
            raise ValueError("created_at_ms cannot be negative")
        if self.reservation_state not in ("queued", "in_use"):
            raise ValueError("reservation_state must be queued or in_use")


def order_submission_key(order: QueuedOrder) -> tuple[int, int, int, int]:
    """priority, FEFO, 접수시각, job ID 순의 canonical key."""
    expiry = (
        order.earliest_item_expiry_ms
        if order.earliest_item_expiry_ms is not None
        else _MAX_MILLIS
    )
    return (
        _PRIORITY_RANK[order.priority],
        expiry,
        order.created_at_ms,
        order.job_id,
    )


def reorder_unsubmitted(
    orders: tuple[QueuedOrder, ...],
) -> tuple[QueuedOrder, ...]:
    """queued 항목만 정렬하고 in_use 항목의 index는 보존한다."""
    queued = iter(
        sorted(
            (order for order in orders if order.reservation_state == "queued"),
            key=order_submission_key,
        )
    )
    return tuple(
        order if order.reservation_state == "in_use" else next(queued)
        for order in orders
    )
