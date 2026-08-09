"""작업·비상 감사 이력의 영속성 인수 테스트."""
from __future__ import annotations

import unittest

from control_tower.database.repositories.audit_repository import AuditRepository


class AuditRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = AuditRepository(':memory:')

    def tearDown(self) -> None:
        self.repo.close()

    def test_records_stage_boundaries_and_administrator_intervention(self) -> None:
        """Task history retains who changed which stage and at what time."""
        self.repo.record_stage('job-1', 'order-1', 'PK-01', 'PICK', 'STARTED', occurred_at_s=10)
        self.repo.record_stage('job-1', 'order-1', 'PK-01', 'PICK', 'COMPLETED', occurred_at_s=20)
        self.repo.record_intervention('job-1', request_id='hold-1', operator_id='admin-1', action='HOLD', reason='area check', occurred_at_s=21)
        history = self.repo.job_history('job-1')
        self.assertEqual(('PICK:STARTED', 'PICK:COMPLETED', 'INTERVENTION:HOLD'), tuple(event.kind for event in history))
        self.assertEqual('admin-1', history[-1].operator_id)

    def test_retried_intervention_is_recorded_once_by_request_id(self) -> None:
        """REST/WebSocket retries do not duplicate an administrator action."""
        self.assertTrue(self.repo.record_intervention('job-1', request_id='cancel-1', operator_id='admin-1', action='CANCEL', reason='operator request', occurred_at_s=10))
        self.assertFalse(self.repo.record_intervention('job-1', request_id='cancel-1', operator_id='admin-1', action='CANCEL', reason='operator request', occurred_at_s=11))
        self.assertEqual(1, len(self.repo.job_history('job-1')))

    def test_incident_requires_approval_record_before_release(self) -> None:
        """Emergency zones cannot be silently cleared without an attributable approval."""
        self.repo.open_incident('incident-1', camera_id='cam-1', location_id='cold-a', occurred_at_s=100)
        with self.assertRaises(ValueError):
            self.repo.release_incident('incident-1', operator_id='', approved_at_s=110)
        self.repo.release_incident('incident-1', operator_id='admin-1', approved_at_s=110)
        incident = self.repo.incident('incident-1')
        self.assertEqual('RELEASED', incident.state)
        self.assertEqual('admin-1', incident.approved_by)


if __name__ == '__main__':
    unittest.main()
