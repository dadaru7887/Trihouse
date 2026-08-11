"""RMF adapter 좁은 통로 시간 예약의 인수 테스트."""

import unittest

from control_tower.rmf_adapter.traffic_reservation import TrafficReservationBook, TrafficRequest


class TrafficReservationBookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.book = TrafficReservationBook()

    def test_overlapping_narrow_aisle_request_waits_at_registered_node(self) -> None:
        """A second Pinky never enters the same single-capacity aisle time window."""
        first = self.book.reserve(TrafficRequest('PK-01', 'AISLE-7', 10, 20, priority=1, waiting_node_id='WAIT-A'))
        second = self.book.reserve(TrafficRequest('PK-02', 'AISLE-7', 12, 18, priority=1, waiting_node_id='WAIT-B'))
        self.assertEqual((10, 20), (first.start_s, first.end_s))
        self.assertEqual((20, 26), (second.start_s, second.end_s))
        self.assertEqual('WAIT-B', second.waiting_node_id)

    def test_priority_orders_uncommitted_batch_but_does_not_preempt_existing_entry(self) -> None:
        """Urgent work wins scheduling order without interrupting an already reserved robot."""
        decisions = self.book.schedule([
            TrafficRequest('PK-01', 'AISLE-7', 10, 20, priority=1, waiting_node_id='WAIT-A'),
            TrafficRequest('PK-02', 'AISLE-7', 10, 20, priority=2, waiting_node_id='WAIT-B'),
        ])
        self.assertEqual('PK-02', decisions[0].robot_id)
        later = self.book.reserve(TrafficRequest('PK-03', 'AISLE-7', 11, 15, priority=3, waiting_node_id='WAIT-C'))
        self.assertGreaterEqual(later.start_s, 20)

    def test_release_allows_next_robot_to_use_the_freed_interval(self) -> None:
        """A cancellation/exit releases only that robot's corridor reservation."""
        self.book.reserve(TrafficRequest('PK-01', 'AISLE-7', 10, 20, priority=1, waiting_node_id='WAIT-A'))
        self.book.release(robot_id='PK-01', resource_id='AISLE-7')
        next_entry = self.book.reserve(TrafficRequest('PK-02', 'AISLE-7', 12, 18, priority=1, waiting_node_id='WAIT-B'))
        self.assertEqual((12, 18), (next_entry.start_s, next_entry.end_s))


if __name__ == '__main__':
    unittest.main()
