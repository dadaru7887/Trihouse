"""OMX 상태 heartbeat와 즉시 발행 주기의 인수 테스트."""
from __future__ import annotations

import unittest

from control_tower.gateway.omx_status import OmxStatus, OmxStatusPublisher


class OmxStatusPublisherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.publisher = OmxStatusPublisher(period_s=1.0)
        self.ready = OmxStatus('OMX-01', 'job-1', 'PICK', True, 'IDLE', False, True, False, '')

    def test_publishes_initially_then_each_second_when_unchanged(self) -> None:
        """FMS receives baseline status every second even during a long stable wait."""
        self.assertTrue(self.publisher.should_publish(self.ready, now_s=0))
        self.assertFalse(self.publisher.should_publish(self.ready, now_s=0.5))
        self.assertTrue(self.publisher.should_publish(self.ready, now_s=1.0))

    def test_stage_or_safety_change_publishes_immediately(self) -> None:
        """A new pick stage or safety fault does not wait for the next heartbeat."""
        self.publisher.should_publish(self.ready, now_s=0)
        moving = OmxStatus('OMX-01', 'job-1', 'PICK', True, 'MOVING', False, True, False, '')
        self.assertTrue(self.publisher.should_publish(moving, now_s=0.1))
        fault = OmxStatus('OMX-01', 'job-1', 'PICK', True, 'MOVING', False, False, True, 'joint limit')
        self.assertTrue(self.publisher.should_publish(fault, now_s=0.2))


if __name__ == '__main__':
    unittest.main()
