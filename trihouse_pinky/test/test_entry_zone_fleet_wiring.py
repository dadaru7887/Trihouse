"""Fleet 실행 흐름에서 entry-zone handoff와 pose 정렬의 배선 계약."""

from pathlib import Path


PINKY = Path(__file__).resolve().parents[1]
FLEET_NODE = (
    PINKY / "trihouse_pinky_fleet" / "trihouse_pinky_fleet" / "fleet_node.py"
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
