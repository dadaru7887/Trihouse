"""외부 장비 없이 FMS 정책 module을 잇는 출고 end-to-end 시나리오."""

from datetime import date
import unittest

from control_tower.fleet_manager.dispatch_workflow import DispatchWorkflow, RobotSnapshot, TaskRequest
from control_tower.fleet_manager.inventory_workflow import InventoryWorkflow, StockLot
from control_tower.fleet_manager.packing_station import PackingStationPolicy
from control_tower.task_manager.handover_gate import HandoverGate
from control_tower.task_manager.omx_workflow import OmxWorkflow
from control_tower.task_manager.stage_engine import JobState, StageEngine


class OutboundHappyPathTest(unittest.TestCase):
    def test_one_reserved_item_reaches_packing_then_changes_inventory_once(self) -> None:
        """An item moves only after both robots are ready and is decremented at handover only."""
        inventory = InventoryWorkflow()
        inventory.add_lot(StockLot('lot-1', 'milk', 1, date(2026, 8, 20), 'CHILLED', 'S-01', 'A-01'))
        self.assertEqual(('lot-1',), inventory.reserve_outbound('job-1', 'milk', 1))

        dispatch = DispatchWorkflow()
        dispatch.upsert_robot(RobotSnapshot('PK-01', True, 80, 0, False))
        self.assertEqual('PK-01', dispatch.assign(TaskRequest('job-1', 1, 1, 'OMX-01')))

        stages = StageEngine(); stages.create('job-1', stages=('PICK', 'LOAD', 'TRANSPORT', 'HANDOVER'))
        handover = HandoverGate(); handover.expect('job-1', pinky_id='PK-01', omx_id='OMX-01')
        handover.mark_ready('job-1', robot_id='PK-01', role='PINKY')
        self.assertFalse(handover.can_start('job-1'))
        handover.mark_ready('job-1', robot_id='OMX-01', role='OMX')

        omx = OmxWorkflow(retry_offsets=((0.0, 0.0),))
        omx.start('job-1', order_id='order-1', expected_items=('milk-1',))
        self.assertTrue(omx.authorize_pick('job-1', 'milk-1', qr_matches=True, marker_valid=True).accepted)
        omx.pick_succeeded('job-1', 'milk-1')
        self.assertTrue(omx.confirm_handover('job-1', loaded_items=('milk-1',), gripper_open=True, retreated=True).accepted)
        self.assertTrue(stages.complete('job-1', stage_id='PICK', result_id='pick-done'))
        self.assertTrue(stages.complete('job-1', stage_id='LOAD', result_id='load-done'))

        stations = PackingStationPolicy(); stations.register('PACK-1', worker_present=True)
        stations.reserve('PACK-1', job_id='job-1', robot_id='PK-01')
        stations.arrive('PACK-1', job_id='job-1', robot_id='PK-01')
        self.assertTrue(stages.complete('job-1', stage_id='TRANSPORT', result_id='transport-done'))
        inventory.finalize_outbound('job-1', {'lot-1': 1})
        self.assertTrue(stages.complete('job-1', stage_id='HANDOVER', result_id='handover-done'))
        stations.release('PACK-1', job_id='job-1')

        self.assertEqual(0, inventory.physical_quantity('milk'))
        self.assertEqual(JobState.COMPLETED, stages.state_of('job-1'))


if __name__ == '__main__':
    unittest.main()
