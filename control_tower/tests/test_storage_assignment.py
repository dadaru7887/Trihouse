"""QR 값만 쓰는 입고 보관 구역 배정의 인수 테스트."""
from __future__ import annotations

import unittest

from control_tower.fleet_manager.storage_assignment import StorageAssignmentPolicy


class StorageAssignmentPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = StorageAssignmentPolicy({'AMBIENT': 'ROOM', 'CHILLED': 'CHILLED', 'FROZEN': 'FROZEN'})

    def test_only_registered_qr_storage_code_assigns_a_zone(self) -> None:
        """FMS uses QR storage code, never an inferred product attribute."""
        result = self.policy.assign('CHILLED')
        self.assertTrue(result.assigned)
        self.assertEqual('CHILLED', result.zone)

    def test_missing_or_unknown_code_holds_inbound_without_slot_search(self) -> None:
        """Invalid QR data becomes an inbound hold instead of a guessed warehouse zone."""
        self.assertFalse(self.policy.assign(None).assigned)
        self.assertFalse(self.policy.assign('MEDICINE').assigned)
        self.assertEqual('INBOUND_HOLD', self.policy.assign('MEDICINE').state)


if __name__ == '__main__':
    unittest.main()
