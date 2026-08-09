"""재고 예약과 fleet 배차 전에 주문을 확정하는 정책.

이 모듈은 재고를 차감하지 않는다. 실제 lot 예약은 다음 단계인
``InventoryWorkflow.reserve_outbound``만 수행한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class OrderIntakeState(StrEnum):
    """요청 수량을 검증한 직후의 주문 상태."""

    QUEUED = 'QUEUED'
    CANCELLED = 'CANCELLED'


@dataclass(frozen=True)
class RequestedItem:
    item_id: str
    quantity: int


@dataclass(frozen=True)
class OrderIntakeResult:
    order_id: str
    state: OrderIntakeState
    confirmed: tuple[RequestedItem, ...]
    destination_id: str
    fulfillment_mode: str


class OrderIntakePolicy:
    """재고 snapshot에서 전량 또는 허용된 부분 출고 수량을 확정한다."""

    def accept(
        self,
        *,
        order_id: str,
        requested: tuple[RequestedItem, ...],
        available: Mapping[str, int],
        allow_partial: bool,
        destination_id: str,
        fulfillment_mode: str,
    ) -> OrderIntakeResult:
        self._validate(order_id, requested, destination_id, fulfillment_mode)

        confirmed = tuple(
            RequestedItem(item.item_id, min(item.quantity, max(0, available.get(item.item_id, 0))))
            for item in requested
            if available.get(item.item_id, 0) > 0
        )
        has_shortage = any(
            max(0, available.get(item.item_id, 0)) < item.quantity
            for item in requested
        )

        if (has_shortage and not allow_partial) or not confirmed:
            return OrderIntakeResult(
                order_id=order_id,
                state=OrderIntakeState.CANCELLED,
                confirmed=(),
                destination_id=destination_id,
                fulfillment_mode=fulfillment_mode,
            )

        return OrderIntakeResult(
            order_id=order_id,
            state=OrderIntakeState.QUEUED,
            confirmed=confirmed,
            destination_id=destination_id,
            fulfillment_mode=fulfillment_mode,
        )

    @staticmethod
    def _validate(
        order_id: str,
        requested: tuple[RequestedItem, ...],
        destination_id: str,
        fulfillment_mode: str,
    ) -> None:
        if not all((order_id, destination_id, fulfillment_mode)):
            raise ValueError('order_id, destination_id, and fulfillment_mode are required')
        if not requested:
            raise ValueError('at least one requested item is required')
        if len({item.item_id for item in requested}) != len(requested):
            raise ValueError('requested item IDs must be unique')
        if any(not item.item_id or item.quantity <= 0 for item in requested):
            raise ValueError('each requested item needs an ID and positive quantity')
