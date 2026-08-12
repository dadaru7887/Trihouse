import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trihouse_rmf_bridge.execution import ExecutionRegistry


def test_finish_is_emitted_exactly_once_for_current_execution() -> None:
    registry = ExecutionRegistry()
    token = object()

    assert registry.start(token, "cmd-1").accepted
    assert registry.finish("cmd-1").should_finish_rmf
    assert not registry.finish("cmd-1").should_finish_rmf


def test_stopped_command_ignores_late_result() -> None:
    registry = ExecutionRegistry()
    token = object()
    registry.start(token, "cmd-1")

    stopped = registry.stop(token)

    assert stopped.should_cancel_pinky
    assert not registry.finish("cmd-1").should_finish_rmf


def test_replaced_command_ignores_previous_result() -> None:
    registry = ExecutionRegistry()
    first = object()
    second = object()
    registry.start(first, "cmd-1")

    replaced = registry.start(second, "cmd-2")

    assert replaced.accepted
    assert replaced.replaced_command_id == "cmd-1"
    assert not registry.finish("cmd-1").should_finish_rmf
    assert registry.finish("cmd-2").should_finish_rmf


def test_stop_for_different_activity_does_not_cancel_current_command() -> None:
    registry = ExecutionRegistry()
    current = object()
    registry.start(current, "cmd-1")

    stopped = registry.stop(object())

    assert not stopped.should_cancel_pinky
    assert registry.finish("cmd-1").should_finish_rmf


def test_current_command_id_changes_atomically_with_lifecycle() -> None:
    registry = ExecutionRegistry()
    token = object()

    assert registry.current_command_id() == ""
    registry.start(token, "cmd-1")
    assert registry.current_command_id() == "cmd-1"
    registry.stop(token)
    assert registry.current_command_id() == ""
