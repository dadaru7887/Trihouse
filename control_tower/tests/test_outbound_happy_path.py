"""외부 장비 없이 출고 정책과 새 작업 오케스트레이션을 잇는 시나리오."""

from datetime import date
import unittest

from control_tower.fleet_manager.dispatch_workflow import DispatchWorkflow, RobotSnapshot, TaskRequest
from control_tower.fleet_manager.inventory_workflow import InventoryWorkflow, StockLot
from control_tower.fleet_manager.packing_station import PackingStationPolicy
from control_tower.task_manager.execution_result import ActorRole
from control_tower.task_manager.execution_store import InMemoryExecutionStore
from control_tower.task_manager.omx_workflow import OmxWorkflow
from control_tower.task_manager.stage_engine import JobState
from control_tower.task_manager.task_orchestrator import StageSpec, TaskOrchestrator
from control_tower.tests.orchestration_fixtures import successful_completion


class OutboundHappyPathTest(unittest.TestCase):
    def test_one_reserved_item_reaches_packing_then_changes_inventory_once(self) -> None:
        """양쪽 준비 이후 단계가 순서대로 진행되고 인계 때만 재고를 차감한다."""
        inventory = InventoryWorkflow()
        inventory.add_lot(StockLot('lot-1', 'milk', 1, date(2026, 8, 20), 'CHILLED', 'S-01', 'A-01'))
        self.assertEqual(('lot-1',), inventory.reserve_outbound('job-1', 'milk', 1))

        dispatch = DispatchWorkflow()
        dispatch.upsert_robot(RobotSnapshot('PK-01', True, 80, 0, False))
        self.assertEqual('PK-01', dispatch.assign(TaskRequest('job-1', 1, 1, 'OMX-01')))

        store = InMemoryExecutionStore()
        tasks = TaskOrchestrator(store=store)
        tasks.create('job-1', stages=(
            StageSpec('READY', frozenset({ActorRole.PINKY, ActorRole.OMX})),
            StageSpec('PICK', frozenset({ActorRole.OMX}), 'START_PICK', ActorRole.OMX, 'QR_MARKER_PICK'),
            StageSpec('LOAD', frozenset({ActorRole.OMX}), 'START_LOAD', ActorRole.OMX, 'BASKET_LOAD'),
            StageSpec('TRANSPORT', frozenset({ActorRole.PINKY}), 'NAVIGATE_PACKING', ActorRole.PINKY, 'RMF_NAVIGATE'),
            StageSpec('HANDOVER', frozenset({ActorRole.OMX}), 'CONFIRM_HANDOVER', ActorRole.OMX, 'OMX_HANDOVER'),
        ))
        tasks.assign('job-1', assignment_revision=1, actors={ActorRole.PINKY: 'PK-01', ActorRole.OMX: 'OMX-01'})
        tasks.start('job-1', safety_approved=True)

        pinky_ready = successful_completion('READY', ActorRole.PINKY, 'PK-01', 'ready-pinky')
        omx_ready = successful_completion('READY', ActorRole.OMX, 'OMX-01', 'ready-omx')
        self.assertEqual((), tasks.record_completion(*pinky_ready, safety_approved=True).commands)
        self.assertEqual('START_PICK', tasks.record_completion(*omx_ready, safety_approved=True).commands[0].command_kind)

        omx = OmxWorkflow(retry_offsets=((0.0, 0.0),))
        omx.start('job-1', order_id='order-1', expected_items=('milk-1',))
        self.assertTrue(omx.authorize_pick('job-1', 'milk-1', qr_matches=True, marker_valid=True).accepted)
        omx.pick_succeeded('job-1', 'milk-1')
        pick_done = successful_completion('PICK', ActorRole.OMX, 'OMX-01', 'pick-done')
        self.assertEqual('START_LOAD', tasks.record_completion(*pick_done, safety_approved=True).commands[0].command_kind)
        self.assertTrue(omx.confirm_handover('job-1', loaded_items=('milk-1',), gripper_open=True, retreated=True).accepted)
        load_done = successful_completion('LOAD', ActorRole.OMX, 'OMX-01', 'load-done')
        self.assertEqual('NAVIGATE_PACKING', tasks.record_completion(*load_done, safety_approved=True).commands[0].command_kind)

        stations = PackingStationPolicy(); stations.register('PACK-1', worker_present=True)
        stations.reserve('PACK-1', job_id='job-1', robot_id='PK-01')
        stations.arrive('PACK-1', job_id='job-1', robot_id='PK-01')
        transport_done = successful_completion('TRANSPORT', ActorRole.PINKY, 'PK-01', 'transport-done')
        self.assertEqual('CONFIRM_HANDOVER', tasks.record_completion(*transport_done, safety_approved=True).commands[0].command_kind)
        inventory.finalize_outbound('job-1', {'lot-1': 1})
        handover_done = successful_completion('HANDOVER', ActorRole.OMX, 'OMX-01', 'handover-done')
        self.assertEqual((), tasks.record_completion(*handover_done, safety_approved=True).commands)
        stations.release('PACK-1', job_id='job-1')

        self.assertEqual(0, inventory.physical_quantity('milk'))
        self.assertEqual(JobState.COMPLETED, tasks.job_state('job-1'))
        self.assertEqual(4, len(store.commands))


if __name__ == '__main__':
    unittest.main()
