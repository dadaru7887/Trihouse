"""출고 주문 접수와 재고 부족 정책의 인수 테스트."""
from __future__ import annotations

import unittest

from control_tower.fleet_manager.order_intake import OrderIntakePolicy, OrderIntakeState, RequestedItem


class OrderIntakePolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = OrderIntakePolicy()

    def test_full_order_with_sufficient_stock_becomes_queued_work(self) -> None:
        """Confirmed items reserve workflow data while original stock remains unchanged."""
        result = self.policy.accept(
            order_id='order-1', requested=(RequestedItem('milk', 3),), available={'milk': 3},
            allow_partial=False, destination_id='PACK-1', fulfillment_mode='PACKING',
        )
        self.assertEqual(OrderIntakeState.QUEUED, result.state)
        self.assertEqual((RequestedItem('milk', 3),), result.confirmed)

    def test_partial_order_confirms_only_available_items(self) -> None:
        """Partial fulfillment does not invent unavailable inventory or cancel available work."""
        result = self.policy.accept(
            order_id='order-1', requested=(RequestedItem('milk', 3), RequestedItem('yogurt', 2)),
            available={'milk': 1, 'yogurt': 2}, allow_partial=True, destination_id='PACK-1', fulfillment_mode='PACKING',
        )
        self.assertEqual(OrderIntakeState.QUEUED, result.state)
        self.assertEqual((RequestedItem('milk', 1), RequestedItem('yogurt', 2)), result.confirmed)

    def test_full_only_order_cancels_without_creating_robot_work_when_stock_is_short(self) -> None:
        """All-or-nothing orders stop before FMS dispatch if any requested quantity is missing."""
        result = self.policy.accept(
            order_id='order-1', requested=(RequestedItem('milk', 3),), available={'milk': 2},
            allow_partial=False, destination_id='PACK-1', fulfillment_mode='PACKING',
        )
        self.assertEqual(OrderIntakeState.CANCELLED, result.state)
        self.assertEqual((), result.confirmed)


if __name__ == '__main__':
    unittest.main()
