"""Control Tower→OMX NDJSON message의 인수 테스트."""
from __future__ import annotations

import unittest

from control_tower.gateway.omx_protocol import OmxMessageGate, ProtocolError, parse_omx_command, parse_omx_result


class OmxProtocolTest(unittest.TestCase):
    def test_pick_command_requires_traceable_job_item_and_shelf_context(self) -> None:
        """An OMX command cannot move an arm without the FMS reservation identity."""
        command = parse_omx_command({
            'type': 'omx_pick', 'message_id': 'cmd-1', 'job_id': 'job-1', 'job_step_id': 'pick-1',
            'order_id': 'order-1', 'item_id': 'item-1', 'shelf_id': 'S-01', 'slot_id': 'A-02',
        })
        self.assertEqual('item-1', command.item_id)
        with self.assertRaises(ProtocolError):
            parse_omx_command({'type': 'omx_pick', 'message_id': 'cmd-2', 'job_id': 'job-1'})

    def test_result_requires_matching_command_identity_and_is_idempotent(self) -> None:
        """A stale OMX completion never advances another step; duplicate packets are harmless."""
        gate = OmxMessageGate()
        gate.register_command(parse_omx_command({
            'type': 'omx_pick', 'message_id': 'cmd-1', 'job_id': 'job-1', 'job_step_id': 'pick-1',
            'order_id': 'order-1', 'item_id': 'item-1', 'shelf_id': 'S-01', 'slot_id': 'A-02',
        }))
        result = parse_omx_result({'type': 'omx_result', 'message_id': 'result-1', 'command_id': 'cmd-1', 'job_id': 'job-1', 'job_step_id': 'pick-1', 'success': True})
        self.assertTrue(gate.accept_result(result))
        self.assertFalse(gate.accept_result(result))
        stale = parse_omx_result({'type': 'omx_result', 'message_id': 'result-2', 'command_id': 'cmd-1', 'job_id': 'job-1', 'job_step_id': 'load-1', 'success': True})
        self.assertFalse(gate.accept_result(stale))


if __name__ == '__main__':
    unittest.main()
