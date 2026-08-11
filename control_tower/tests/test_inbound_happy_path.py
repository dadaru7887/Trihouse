"""외부 장비 없이 입고 정책과 새 작업 오케스트레이션을 잇는 시나리오."""

from datetime import date
import unittest

from control_tower.fleet_manager.dispatch_workflow import DispatchWorkflow, RobotSnapshot, TaskRequest
from control_tower.fleet_manager.inventory_workflow import InventoryWorkflow
from control_tower.fleet_manager.storage_assignment import StorageAssignmentPolicy
from control_tower.task_manager.execution_result import ActorRole
from control_tower.task_manager.execution_store import InMemoryExecutionStore
from control_tower.task_manager.stage_engine import JobState
from control_tower.task_manager.task_orchestrator import StageSpec, TaskOrchestrator
from control_tower.tests.orchestration_fixtures import successful_completion


class InboundHappyPathTest(unittest.TestCase):
    def test_qr_zone_to_shelf_placement_updates_stock_only_after_omx_completion(self) -> None:
        """양쪽 준비 후 이동·적재가 순서대로 완료된 때만 입고 재고를 생성한다."""
        assignment = StorageAssignmentPolicy({'CHILLED': 'CHILLED'}).assign('CHILLED')
        self.assertTrue(assignment.assigned)

        inventory = InventoryWorkflow()
        inventory.add_slot('CHILLED', 'S-01', 'A-01')
        self.assertEqual(('S-01', 'A-01'), inventory.reserve_inbound_slot('job-1', assignment.zone))

        dispatch = DispatchWorkflow()
        dispatch.upsert_robot(RobotSnapshot('PK-01', True, 80, 0, False))
        self.assertEqual('PK-01', dispatch.assign(TaskRequest('job-1', 1, 1, 'OMX-01')))

        store = InMemoryExecutionStore()
        tasks = TaskOrchestrator(store=store)
        tasks.create('job-1', stages=(
            StageSpec('READY', frozenset({ActorRole.PINKY, ActorRole.OMX})),
            StageSpec('TRANSPORT', frozenset({ActorRole.PINKY}), 'NAVIGATE_STORAGE', ActorRole.PINKY, 'RMF_NAVIGATE'),
            StageSpec('PLACE_SHELF', frozenset({ActorRole.OMX}), 'START_PLACE', ActorRole.OMX, 'MARKER_SHELF_PLACE'),
        ))
        tasks.assign('job-1', assignment_revision=1, actors={ActorRole.PINKY: 'PK-01', ActorRole.OMX: 'OMX-01'})
        tasks.start('job-1', safety_approved=True)

        pinky_ready = successful_completion('READY', ActorRole.PINKY, 'PK-01', 'ready-pinky')
        omx_ready = successful_completion('READY', ActorRole.OMX, 'OMX-01', 'ready-omx')
        self.assertEqual((), tasks.record_completion(*pinky_ready, safety_approved=True).commands)
        transport_command = tasks.record_completion(*omx_ready, safety_approved=True).commands[0]
        self.assertEqual('NAVIGATE_STORAGE', transport_command.command_kind)

        transport_done = successful_completion('TRANSPORT', ActorRole.PINKY, 'PK-01', 'arrived', transport_command)
        place_command = tasks.record_completion(*transport_done, safety_approved=True).commands[0]
        self.assertEqual('START_PLACE', place_command.command_kind)
        self.assertEqual(0, inventory.physical_quantity('ice-cream'))
        placed = successful_completion('PLACE_SHELF', ActorRole.OMX, 'OMX-01', 'placed', place_command)
        self.assertEqual((), tasks.record_completion(*placed, safety_approved=True).commands)
        inventory.finalize_inbound('job-1', 'lot-1', 'ice-cream', 2, date(2026, 9, 1))

        self.assertEqual(2, inventory.physical_quantity('ice-cream'))
        self.assertEqual(('S-01', 'A-01'), inventory.location_of('lot-1'))
        self.assertEqual(JobState.COMPLETED, tasks.job_state('job-1'))
        self.assertEqual(2, len(store.commands))


if __name__ == '__main__':
    unittest.main()
