"""Fleet 실행 흐름에서 entry-zone handoff와 pose 정렬의 배선 계약."""

import sys
from pathlib import Path
from types import SimpleNamespace


PINKY = Path(__file__).resolve().parents[1]
FLEET_NODE = (
    PINKY / "trihouse_pinky_fleet" / "trihouse_pinky_fleet" / "fleet_node.py"
)
sys.path.insert(0, str(PINKY / "trihouse_pinky_docking"))
sys.path.insert(0, str(PINKY / "trihouse_pinky_fleet"))

from trihouse_interfaces.msg import SafetyState  # noqa: E402
from trihouse_pinky_docking.narrow_zone import SafetyObservation  # noqa: E402
from trihouse_pinky_fleet.fleet_node import FleetNode  # noqa: E402
from trihouse_pinky_fleet.workflow import (  # noqa: E402
    JobCommand,
    JobPhase,
    TransportWorkflow,
)


def _execute_source() -> str:
    source = FLEET_NODE.read_text(encoding="utf-8")
    return source.split("    async def _execute(", 1)[1].split(
        "\n    def _recovery_pose", 1
    )[0]


def test_execute_awaits_entry_zone_instead_of_only_waiting_for_nav2_result() -> None:
    """Nav2 결과만 기다려 입구 최종 회전에서 멈추는 결함을 잡는다."""
    execute = _execute_source()

    assert "await self._await_nav_or_entry_handoff(" in execute
    assert "nav_handle.get_result_async()" not in execute


def test_execute_aligns_entry_pose_before_running_measured_dock_steps() -> None:
    """구역 경계 pose에서 곧바로 20cm를 진행해 도크가 어긋나는 결함을 잡는다."""
    execute = _execute_source()

    align = execute.index("EntryPoseController(")
    measured_steps = execute.index("NarrowZoneController(", align)

    assert align < measured_steps


def test_safety_callback_preserves_stop_detail_for_rule_controller() -> None:
    workflow = SimpleNamespace(enter_emergency=lambda _detail: None)
    node = SimpleNamespace(
        safety_seen=False,
        emergency=False,
        safety_observation=SafetyObservation(),
        workflow=workflow,
    )
    message = SimpleNamespace(state=SafetyState.STATE_STOP, detail="swept_stop")

    FleetNode._on_safety(node, message)

    assert node.safety_seen is True
    assert node.emergency is False
    assert node.safety_observation == SafetyObservation(
        stopped=True, emergency=False, detail="swept_stop"
    )


def test_local_rule_failure_releases_workflow_for_the_next_command() -> None:
    workflow = TransportWorkflow(robot_id="PK_01", expected_map_revision="map-v1")
    first = JobCommand("command-1", "job-1", "map-v1", "WAREHOUSE")
    assert workflow.accept(first, ready=True, cargo_confirmed=True).accepted
    node = SimpleNamespace(workflow=workflow, stationary=True)

    outcome = FleetNode._release_rule_failure(node)

    assert outcome.phase is JobPhase.IDLE
    second = JobCommand("command-2", "job-2", "map-v1", "WAREHOUSE")
    assert workflow.accept(second, ready=True, cargo_confirmed=True).accepted
