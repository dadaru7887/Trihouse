"""Architecture boundary tests for the new Control Tower runtime path."""

import ast
import builtins
import importlib
import inspect
import sys

import control_tower.gateway.fms_client as fms_client
import control_tower.task_manager.job_runner as job_runner
import control_tower.task_manager.outbound_sequence as outbound_sequence
import control_tower.task_manager.sequence_orchestrator as sequence_orchestrator
import control_tower.rmf_adapter.rmf_gateway_worker as rmf_gateway_worker
import control_tower.rmf_adapter.rmf_gateway_worker_node as rmf_gateway_worker_node


def test_sequence_runtime_sources_import_no_database_client_or_repository() -> None:
    """Deferred or aliased DB imports must fail without executing the source."""
    imported_names: set[str] = set()
    for module in (
        fms_client,
        job_runner,
        outbound_sequence,
        sequence_orchestrator,
        rmf_gateway_worker,
        rmf_gateway_worker_node,
    ):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.update(alias.name.lower() for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_names.add((node.module or "").lower())

    forbidden = {"mysql", "pymysql", "database", "repository", "repositories"}
    assert not {
        imported
        for imported in imported_names
        if forbidden.intersection(imported.split("."))
    }


def test_sequence_orchestrator_import_graph_excludes_database_repositories(
    monkeypatch,
) -> None:
    """The runtime module must remain loadable when all DB imports are forbidden."""
    original_import = builtins.__import__

    def reject_database_import(
        name: str,
        globals_: object = None,
        locals_: object = None,
        fromlist: tuple[str, ...] | None = (),
        level: int = 0,
    ) -> object:
        requested = (name, *(f"{name}.{item}" for item in (fromlist or ())))
        forbidden_parts = {"database", "repositories", "repository"}
        if any(
            module.lower().startswith("mysql")
            or forbidden_parts.intersection(module.lower().split("."))
            for module in requested
        ):
            raise AssertionError(f"database boundary crossed by import: {name}")
        return original_import(name, globals_, locals_, fromlist, level)

    for module_name in (
        "control_tower.task_manager.sequence_orchestrator",
        "control_tower.task_manager.outbound_sequence",
        "control_tower.gateway.fms_client",
    ):
        sys.modules.pop(module_name, None)
    monkeypatch.setattr(builtins, "__import__", reject_database_import)

    imported = importlib.import_module("control_tower.task_manager.sequence_orchestrator")

    assert imported.SequenceOrchestrator.__module__ == imported.__name__


def test_job_runner_import_graph_excludes_database_repositories(monkeypatch) -> None:
    """The runner reaches the Gateway over HTTP only; it must never touch the DB."""
    original_import = builtins.__import__

    def reject_database_import(
        name: str,
        globals_: object = None,
        locals_: object = None,
        fromlist: tuple[str, ...] | None = (),
        level: int = 0,
    ) -> object:
        requested = (name, *(f"{name}.{item}" for item in (fromlist or ())))
        forbidden_parts = {"database", "repositories", "repository"}
        if any(
            module.lower().startswith("mysql")
            or forbidden_parts.intersection(module.lower().split("."))
            for module in requested
        ):
            raise AssertionError(f"database boundary crossed by import: {name}")
        return original_import(name, globals_, locals_, fromlist, level)

    for module_name in (
        "control_tower.task_manager.job_runner",
        "control_tower.task_manager.assignment",
        "control_tower.fleet_manager.packing_station",
        "control_tower.gateway.fms_client",
    ):
        sys.modules.pop(module_name, None)
    monkeypatch.setattr(builtins, "__import__", reject_database_import)

    imported = importlib.import_module("control_tower.task_manager.job_runner")

    assert imported.JobRunner.__module__ == imported.__name__


def test_the_job_runner_is_constructed_outside_its_own_module_and_tests() -> None:
    """The defect this runner fixes: orchestration code that nothing ever runs.

    `SequenceOrchestrator` was only ever instantiated by its own tests, so no
    process advanced a queued Job. This asserts the replacement is actually
    wired into a runnable entry point.
    """
    source = inspect.getsource(
        importlib.import_module("control_tower.task_manager.job_runner_node")
    )

    assert "JobRunner(" in source
