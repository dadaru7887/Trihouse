"""UI 전용 Gateway 운영 feed의 인수 테스트."""

import unittest

from control_tower.gateway.operations_feed import IncidentView, JobView, OperationsFeed, RobotView


class OperationsFeedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.feed = OperationsFeed()

    def test_single_snapshot_contains_robot_job_and_incident_views(self) -> None:
        """The UI receives every operational concern from one Gateway boundary."""
        self.feed.upsert_robot(RobotView('PK-01', 1.0, 2.0, 0.5, 75, 'SAFE', 'job-1', 'TRANSPORT', ''))
        self.feed.upsert_job(JobView('job-1', 'order-1', ('item-1',), 'PK-01', 'TRANSPORT', 'RUNNING'))
        self.feed.open_incident(IncidentView('incident-1', 'cam-1', 'cold-a', 100, False))
        snapshot = self.feed.snapshot()
        self.assertEqual('PK-01', snapshot.robots[0].robot_id)
        self.assertEqual('job-1', snapshot.jobs[0].job_id)
        self.assertEqual('incident-1', snapshot.incidents[0].incident_id)

    def test_incident_event_precedes_ordinary_job_event_and_remains_until_release(self) -> None:
        """A fall alert must be visually more prominent than an ordinary task update."""
        self.feed.upsert_job(JobView('job-1', 'order-1', (), 'PK-01', 'PICK', 'FAILED'))
        self.feed.open_incident(IncidentView('incident-1', 'cam-1', 'cold-a', 100, False))
        events = self.feed.drain_events()
        self.assertEqual(('INCIDENT_OPEN', 'JOB_UPDATED'), tuple(event.kind for event in events))
        self.assertEqual('incident-1', self.feed.snapshot().incidents[0].incident_id)
        self.feed.release_incident('incident-1', acknowledged_at_s=110)
        self.assertTrue(self.feed.snapshot().incidents[0].acknowledged)


if __name__ == '__main__':
    unittest.main()
