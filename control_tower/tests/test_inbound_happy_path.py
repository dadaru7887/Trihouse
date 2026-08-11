"""외부 장비 없이 FMS 정책 module을 잇는 입고 end-to-end 시나리오."""

from datetime import date
import unittest

from control_tower.fleet_manager.dispatch_workflow import DispatchWorkflow, RobotSnapshot, TaskRequest
from control_tower.fleet_manager.inventory_workflow import InventoryWorkflow
from control_tower.fleet_manager.storage_assignment import StorageAssignmentPolicy
from control_tower.task_manager.handover_gate import HandoverGate
from control_tower.task_manager.stage_engine import JobState, StageEngine


class InboundHappyPathTest(unittest.TestCase):
    def test_qr_zone_to_shelf_placement_updates_stock_only_after_omx_completion(self) -> None:
        """QR decides zone, while OMX shelf-placement completion creates the final inventory lot."""
        assignment = StorageAssignmentPolicy({'CHILLED': 'CHILLED'}).assign('CHILLED')
        self.assertTrue(assignment.assigned)

        inventory = InventoryWorkflow()
        inventory.add_slot('CHILLED', 'S-01', 'A-01')
        self.assertEqual(('S-01', 'A-01'), inventory.reserve_inbound_slot('job-1', assignment.zone))

        dispatch = DispatchWorkflow()
        dispatch.upsert_robot(RobotSnapshot('PK-01', True, 80, 0, False))
        self.assertEqual('PK-01', dispatch.assign(TaskRequest('job-1', 1, 1, 'OMX-01')))

        stages = StageEngine(); stages.create('job-1', stages=('TRANSPORT', 'PLACE_SHELF'))
        handover = HandoverGate(); handover.expect('job-1', pinky_id='PK-01', omx_id='OMX-01')
        handover.mark_ready('job-1', robot_id='PK-01', role='PINKY')
        handover.mark_ready('job-1', robot_id='OMX-01', role='OMX')
        self.assertTrue(handover.can_start('job-1'))

        self.assertTrue(stages.complete('job-1', stage_id='TRANSPORT', result_id='arrived'))
        self.assertEqual(0, inventory.physical_quantity('ice-cream'))
        inventory.finalize_inbound('job-1', 'lot-1', 'ice-cream', 2, date(2026, 9, 1))
        self.assertTrue(stages.complete('job-1', stage_id='PLACE_SHELF', result_id='placed'))

        self.assertEqual(2, inventory.physical_quantity('ice-cream'))
        self.assertEqual(('S-01', 'A-01'), inventory.location_of('lot-1'))
        self.assertEqual(JobState.COMPLETED, stages.state_of('job-1'))


if __name__ == '__main__':
    unittest.main()
