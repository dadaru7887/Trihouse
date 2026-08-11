"""작업자/운영자가 확인한 출고 전달 결과를 분류하는 정책."""

from dataclasses import dataclass
from enum import StrEnum


class OrderOutcome(StrEnum):
    COMPLETED = 'COMPLETED'
    PARTIALLY_COMPLETED = 'PARTIALLY_COMPLETED'
    FAILED = 'FAILED'


@dataclass(frozen=True)
class OutboundResult:
    order_id: str
    outcome: OrderOutcome
    delivered_items: tuple[str, ...]
    held_items: tuple[str, ...]


class OutboundResultPolicy:
    def __init__(self) -> None:
        self._results: dict[str, OutboundResult] = {}

    def confirm(
        self,
        order_id: str,
        *,
        expected_items: tuple[str, ...],
        delivered_items: tuple[str, ...],
        held_items: tuple[str, ...],
    ) -> OutboundResult:
        if not order_id or not expected_items:
            raise ValueError('order and expected items are required')
        expected, delivered, held = set(expected_items), set(delivered_items), set(held_items)
        if len(expected) != len(expected_items) or len(delivered) != len(delivered_items) or len(held) != len(held_items):
            raise ValueError('item IDs must be unique')
        if delivered & held or delivered | held != expected:
            raise ValueError('every expected item must be exactly delivered or held')
        outcome = OrderOutcome.COMPLETED if delivered == expected else OrderOutcome.FAILED if not delivered else OrderOutcome.PARTIALLY_COMPLETED
        result = OutboundResult(order_id, outcome, delivered_items, held_items)
        previous = self._results.get(order_id)
        if previous is not None:
            if previous != result:
                raise ValueError('order result is already finalized differently')
            return previous
        self._results[order_id] = result
        return result
