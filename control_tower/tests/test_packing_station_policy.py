"""포장대 예약과 작업자 기반 재배정의 인수 테스트."""

import unittest

from control_tower.fleet_manager.packing_station import PackingStationPolicy, StationState


class PackingStationPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = PackingStationPolicy()
        self.policy.register('PACK-1', worker_present=False)
        self.policy.register('PACK-2', worker_present=True)

    def test_reservation_becomes_in_use_only_when_assigned_pinky_arrives(self) -> None:
        """One packing station is exclusive from reservation through handover/cancel."""
        self.policy.reserve('PACK-1', job_id='job-1', robot_id='PK-01')
        self.assertEqual(StationState.RESERVED, self.policy.state_of('PACK-1'))
        self.policy.arrive('PACK-1', job_id='job-1', robot_id='PK-01')
        self.assertEqual(StationState.IN_USE, self.policy.state_of('PACK-1'))
        self.policy.release('PACK-1', job_id='job-1')
        self.assertEqual(StationState.AVAILABLE, self.policy.state_of('PACK-1'))

    def test_worker_presence_does_not_mutate_reservation_without_fms_decision(self) -> None:
        """Vision supplies a signal; only FMS explicitly reserves or releases stations."""
        self.policy.update_worker_presence('PACK-1', present=True)
        self.assertEqual(StationState.AVAILABLE, self.policy.state_of('PACK-1'))

    def test_reassigns_to_available_staffed_station_or_waits(self) -> None:
        """Same job keeps its cargo state while station selection changes."""
        self.policy.reserve('PACK-1', job_id='job-1', robot_id='PK-01')
        choice = self.policy.choose_for_absent_worker('PACK-1', job_id='job-1', robot_id='PK-01', waiting_node_id='WAIT-1')
        self.assertEqual('MOVE_TO_STATION', choice.action)
        self.assertEqual('PACK-2', choice.station_id)
        self.policy.update_worker_presence('PACK-2', present=False)
        choice = self.policy.choose_for_absent_worker('PACK-2', job_id='job-1', robot_id='PK-01', waiting_node_id='WAIT-1')
        self.assertEqual('WAIT_FOR_WORKER', choice.action)
        self.assertEqual('WAIT-1', choice.waiting_node_id)


if __name__ == '__main__':
    unittest.main()
