"""FMS 재고·slot 최종 확정 규칙의 동작 테스트."""

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fleet_manager.inventory_workflow import InventoryWorkflow, StockLot  # noqa: E402


class InventoryWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fms = InventoryWorkflow()
        self.fms.add_slot('COLD', 'S-01', 'A-01')
        self.fms.add_slot('COLD', 'S-01', 'A-02')
        self.fms.add_lot(StockLot('lot-late', 'milk', 3, date(2026, 9, 2), 'COLD', 'S-09', 'Z-01'))
        self.fms.add_lot(StockLot('lot-early', 'milk', 2, date(2026, 8, 20), 'COLD', 'S-09', 'Z-02'))

    def test_intermediate_transport_does_not_change_original_inventory(self) -> None:
        """Picking, loading, and Pinky transport are task state only, never stock mutation."""
        self.fms.record_step('job-1', 'LOADED_TO_PINKY')
        self.assertEqual(5, self.fms.physical_quantity('milk'))

    def test_inbound_slot_reservation_is_exclusive_and_released_on_cancel(self) -> None:
        """Two inbound jobs cannot take the same slot, and cancellation frees it."""
        first = self.fms.reserve_inbound_slot('job-1', 'COLD')
        second = self.fms.reserve_inbound_slot('job-2', 'COLD')
        self.assertEqual(('S-01', 'A-01'), first)
        self.assertEqual(('S-01', 'A-02'), second)
        self.fms.cancel_job('job-1')
        self.assertEqual(('S-01', 'A-01'), self.fms.reserve_inbound_slot('job-3', 'COLD'))

    def test_outbound_reservation_uses_fefo_and_finalization_is_idempotent(self) -> None:
        """Only confirmed handover decrements stock, even if FMS receives the result twice."""
        selected = self.fms.reserve_outbound('job-1', 'milk', 2)
        self.assertEqual(('lot-early',), selected)
        self.assertEqual(5, self.fms.physical_quantity('milk'))
        self.fms.finalize_outbound('job-1', {'lot-early': 2})
        self.fms.finalize_outbound('job-1', {'lot-early': 2})
        self.assertEqual(3, self.fms.available_quantity('milk'))

    def test_inbound_finalization_creates_stock_only_after_omx_reports_placed(self) -> None:
        """A reserved inbound slot does not become inventory before actual shelf placement."""
        self.fms.reserve_inbound_slot('job-1', 'COLD')
        self.fms.finalize_inbound('job-1', 'new-lot', 'ice-cream', 4, date(2026, 10, 1))
        self.assertEqual(4, self.fms.available_quantity('ice-cream'))
        self.assertEqual(('S-01', 'A-01'), self.fms.location_of('new-lot'))


if __name__ == '__main__':
    unittest.main()
