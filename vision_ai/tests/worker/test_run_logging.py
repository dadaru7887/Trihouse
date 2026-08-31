"""Logging must reach a file in the run directory, and tracking must be optional.

    pytest vision_ai/tests/worker/test_run_logging.py

A run left on a server overnight is read from its log afterwards, so the log
has to survive the process. Tracking is the opposite: a missing wandb, or no
network, must never take the training down with it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from vision_ai.utils.run_logging import Tracker, setup_logging


@pytest.fixture(autouse=True)
def _clean_handlers():
    """setup_logging attaches handlers; drop them so tests do not leak into each other."""
    yield
    logger = logging.getLogger("vision_ai")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def test_it_writes_the_log_into_the_run_directory(tmp_path: Path) -> None:
    logger = setup_logging(tmp_path)
    logger.info("preflight ok")
    logger.warning("gate borderline")

    text = (tmp_path / "run.log").read_text(encoding="utf-8")
    assert "preflight ok" in text
    assert "gate borderline" in text


def test_each_line_carries_a_timestamp_and_level(tmp_path: Path) -> None:
    """Reading a finished run means telling stages apart and finding the failure."""
    setup_logging(tmp_path).info("training started")
    line = (tmp_path / "run.log").read_text(encoding="utf-8").splitlines()[0]
    assert "INFO" in line
    assert "training started" in line
    assert line.count(":") >= 2          # HH:MM:SS


def test_calling_it_twice_does_not_duplicate_every_line(tmp_path: Path) -> None:
    """The pipeline may set up logging per stage; lines must not multiply."""
    setup_logging(tmp_path)
    setup_logging(tmp_path).info("once")
    assert (tmp_path / "run.log").read_text(encoding="utf-8").count("once") == 1


# ---------------------------------------------------------------- tracker --

def test_a_disabled_tracker_does_nothing_and_still_works(tmp_path: Path) -> None:
    tracker = Tracker(enabled=False, project="p", name="n", config={}, run_dir=tmp_path)
    assert tracker.active is False
    tracker.log({"loss": 1.0})           # must not raise
    tracker.summary({"map50": 0.5})
    tracker.finish()


def test_a_missing_wandb_disables_tracking_instead_of_failing(tmp_path, monkeypatch) -> None:
    """A server without wandb installed must still train."""
    import vision_ai.utils.run_logging as module

    monkeypatch.setattr(module, "_import_wandb", lambda: None)
    tracker = Tracker(enabled=True, project="p", name="n", config={}, run_dir=tmp_path)
    assert tracker.active is False
    tracker.log({"loss": 1.0})
    tracker.finish()


def test_an_enabled_tracker_initialises_wandb_once_with_the_config(tmp_path, monkeypatch) -> None:
    import vision_ai.utils.run_logging as module

    calls = {"init": [], "log": [], "finish": 0}

    class FakeRun:
        summary: dict = {}

    class FakeWandb:
        run = None

        def init(self, **kwargs):
            calls["init"].append(kwargs)
            FakeWandb.run = FakeRun()
            return FakeWandb.run

        def log(self, values, step=None):
            calls["log"].append((values, step))

        def finish(self):
            calls["finish"] += 1

    monkeypatch.setattr(module, "_import_wandb", lambda: FakeWandb())
    tracker = Tracker(enabled=True, project="proj", name="run-1",
                      config={"epochs": 3}, run_dir=tmp_path)

    assert tracker.active is True
    assert calls["init"][0]["project"] == "proj"
    assert calls["init"][0]["name"] == "run-1"
    assert calls["init"][0]["config"] == {"epochs": 3}

    tracker.log({"loss": 0.4}, step=2)
    tracker.finish()
    assert calls["log"] == [({"loss": 0.4}, 2)]
    assert calls["finish"] == 1


def test_a_tracker_that_fails_to_start_does_not_stop_training(tmp_path, monkeypatch) -> None:
    """No network on the compute node is a normal condition, not a crash."""
    import vision_ai.utils.run_logging as module

    class ExplodingWandb:
        run = None

        def init(self, **kwargs):
            raise RuntimeError("no network")

    monkeypatch.setattr(module, "_import_wandb", lambda: ExplodingWandb())
    tracker = Tracker(enabled=True, project="p", name="n", config={}, run_dir=tmp_path)
    assert tracker.active is False
    tracker.log({"loss": 1.0})


def test_metrics_are_also_written_beside_the_run(tmp_path, monkeypatch) -> None:
    """The dashboard may be unreachable later; the run keeps its own copy."""
    import vision_ai.utils.run_logging as module

    monkeypatch.setattr(module, "_import_wandb", lambda: None)
    tracker = Tracker(enabled=True, project="p", name="n", config={}, run_dir=tmp_path)
    tracker.log({"epoch": 1, "loss": 0.5})
    tracker.log({"epoch": 2, "loss": 0.3})
    tracker.finish()

    rows = [json.loads(line) for line in
            (tmp_path / "metrics.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["loss"] for row in rows] == [0.5, 0.3]
