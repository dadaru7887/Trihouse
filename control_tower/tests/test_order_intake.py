"""출고 주문 접수와 재고 부족 정책의 인수 테스트."""

import unittest

from control_tower.fleet_manager.order_intake import OrderIntakePolicy, OrderIntakeState, RequestedItem


class OrderIntakePolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = OrderIntakePolicy()

    def test_full_order_with_sufficient_stock_becomes_queued_work(self) -> None:
        """Confirmed items reserve workflow data while original stock remains unchanged."""
        result = self.policy.accept(
            order_id='order-1', requested=(RequestedItem('milk', 3),), available={'milk': 3},
            allow_partial=False,
        )
        self.assertEqual(OrderIntakeState.QUEUED, result.state)
        self.assertEqual((RequestedItem('milk', 3),), result.confirmed)
        self.assertEqual((), result.outstanding)

    def test_partial_order_confirms_only_available_items(self) -> None:
        """Partial fulfillment does not invent unavailable inventory or cancel available work."""
        result = self.policy.accept(
            order_id='order-1', requested=(RequestedItem('milk', 3), RequestedItem('yogurt', 2)),
            available={'milk': 1, 'yogurt': 2}, allow_partial=True,
        )
        self.assertEqual(OrderIntakeState.QUEUED, result.state)
        self.assertEqual((RequestedItem('milk', 1), RequestedItem('yogurt', 2)), result.confirmed)
        self.assertEqual((RequestedItem('milk', 2),), result.outstanding)

    def test_full_only_order_cancels_without_creating_robot_work_when_stock_is_short(self) -> None:
        """All-or-nothing orders stop before FMS dispatch if any requested quantity is missing."""
        result = self.policy.accept(
            order_id='order-1', requested=(RequestedItem('milk', 3),), available={'milk': 2},
            allow_partial=False,
        )
        self.assertEqual(OrderIntakeState.CANCELLED, result.state)
        self.assertEqual((), result.confirmed)
        self.assertEqual('INSUFFICIENT_STOCK', result.reason_code)


if __name__ == '__main__':
    unittest.main()
