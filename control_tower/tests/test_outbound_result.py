"""작업자 확인 출고 결과 확정의 인수 테스트."""
from __future__ import annotations

import unittest

from control_tower.task_manager.outbound_result import OutboundResultPolicy, OrderOutcome


class OutboundResultPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = OutboundResultPolicy()

    def test_all_delivered_items_complete_the_order_once(self) -> None:
        """A repeated UI confirmation preserves the original successful result."""
        first = self.policy.confirm('order-1', expected_items=('item-1', 'item-2'), delivered_items=('item-1', 'item-2'), held_items=())
        retry = self.policy.confirm('order-1', expected_items=('item-1', 'item-2'), delivered_items=('item-1', 'item-2'), held_items=())
        self.assertEqual(OrderOutcome.COMPLETED, first.outcome)
        self.assertEqual(first, retry)

    def test_partial_delivery_keeps_held_item_out_of_inventory_decrement(self) -> None:
        """Only operator-confirmed delivered items may be finalized by inventory workflow."""
        result = self.policy.confirm('order-1', expected_items=('item-1', 'item-2'), delivered_items=('item-1',), held_items=('item-2',))
        self.assertEqual(OrderOutcome.PARTIALLY_COMPLETED, result.outcome)
        self.assertEqual(('item-1',), result.delivered_items)
        self.assertEqual(('item-2',), result.held_items)

    def test_missing_result_for_any_item_is_not_silently_completed(self) -> None:
        """An incomplete operator form must remain unresolved rather than infer success."""
        with self.assertRaises(ValueError):
            self.policy.confirm('order-1', expected_items=('item-1', 'item-2'), delivered_items=('item-1',), held_items=())


if __name__ == '__main__':
    unittest.main()
