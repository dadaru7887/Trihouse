"""Control Tower→OMX NDJSON message의 인수 테스트."""

import json
import unittest

from control_tower.gateway.omx_protocol import (
    OmxMessageGate,
    ProtocolError,
    parse_execute_omx_command,
    parse_omx_command,
    parse_omx_result,
)


class OmxProtocolTest(unittest.TestCase):
    def test_execute_command_round_trips_structured_items_deterministically(self) -> None:
        payload = {
            "schema_version": 1,
            "command_uuid": "cmd-7",
            "kind": "load",
            "job_id": 41,
            "job_step_id": 103,
            "assignment_revision": 2,
            "omx_id": "OMX_02",
            "temperature_zone": "frozen",
            "items": [
                {
                    "job_item_id": 501,
                    "product_code": "SKU-ICECONE",
                    "quantity": 1,
                }
            ],
        }

        command = parse_execute_omx_command(payload)

        self.assertEqual("SKU-ICECONE", command.items[0].product_code)
        self.assertEqual(payload, json.loads(command.to_json()))
        self.assertEqual(command, parse_execute_omx_command(command.to_json()))

    def test_execute_command_rejects_unknown_kind_and_invalid_identity(self) -> None:
        base = {
            "schema_version": 1,
            "command_uuid": "cmd-7",
            "kind": "prepare",
            "job_id": 41,
            "job_step_id": 103,
            "assignment_revision": 2,
            "omx_id": "OMX_01",
            "temperature_zone": "chilled",
            "items": [{"job_item_id": 501, "product_code": "SKU-MILK", "quantity": 1}],
        }
        with self.assertRaises(ProtocolError):
            parse_execute_omx_command({**base, "kind": "pick"})
        with self.assertRaises(ProtocolError):
            parse_execute_omx_command({**base, "assignment_revision": 0})
        with self.assertRaises(ProtocolError):
            parse_execute_omx_command({**base, "omx_id": "omx_01"})

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
