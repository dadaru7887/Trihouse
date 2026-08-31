"""Logging and optional wandb tracking for a training run.

    from vision_ai.utils.run_logging import setup_logging, Tracker

    logger = setup_logging(run_dir)
    tracker = Tracker(enabled=args.wandb, project="trihouse-vision",
                      name=run_dir.name, config=config.to_dict(), run_dir=run_dir)
    logger.info("training started")
    tracker.log({"epoch": 1, "loss": 0.5})
    tracker.finish()

Flow: `setup_logging` attaches a stdout handler and a `run.log` handler to the
`vision_ai` logger, so a run left on a server can be read afterwards. `Tracker`
mirrors metrics to wandb and always to `metrics.jsonl` beside the run.

Tracking never takes training down: a missing wandb, a failed init, or a
network that is not there disables it and logs why. Calling wandb.init here
before ultralytics starts means ultralytics reuses this run rather than opening
a second one, so the config and the per-epoch metrics land together.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

LOGGER_NAME = "vision_ai"
LOG_FILE = "run.log"
METRICS_FILE = "metrics.jsonl"

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_TIME = "%Y-%m-%d %H:%M:%S"


def setup_logging(run_dir: Path, level: int = logging.INFO) -> logging.Logger:
    """Send the `vision_ai` logger to stdout and to `run_dir/run.log`.

    Safe to call more than once for the same directory: handlers are keyed by
    their destination, so a second call does not duplicate every line.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    target = (run_dir / LOG_FILE).resolve()

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False        # the root logger would print each line again
    formatter = logging.Formatter(_FORMAT, _TIME)

    existing = {getattr(h, "_vision_ai_target", None) for h in logger.handlers}
    if "stdout" not in existing:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        stream._vision_ai_target = "stdout"
        logger.addHandler(stream)
    if str(target) not in existing:
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setFormatter(formatter)
        handler._vision_ai_target = str(target)
        logger.addHandler(handler)
    return logger


def _import_wandb():
    """Return the wandb module, or None when it is not installed."""
    try:
        import wandb

        return wandb
    except ImportError:
        return None


class Tracker:
    """Mirror metrics to wandb when it is available, to a JSONL file always.

    `active` says whether wandb actually started. Every method works either
    way, so callers never branch on it.
    """

    def __init__(self, enabled: bool, project: str, name: str,
                 config: dict[str, Any], run_dir: Path) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._metrics = self.run_dir / METRICS_FILE
        self._wandb = None
        self.active = False
        logger = logging.getLogger(LOGGER_NAME)

        if not enabled:
            return
        wandb = _import_wandb()
        if wandb is None:
            logger.warning("wandb is not installed; metrics go to %s only", self._metrics)
            return
        try:
            wandb.init(project=project, name=name, config=config,
                       dir=str(self.run_dir))
        except Exception as error:                      # offline node, bad key, ...
            logger.warning("wandb could not start (%s); metrics go to %s only",
                           error, self._metrics)
            return
        self._wandb = wandb
        self.active = True
        logger.info("wandb tracking run %s in project %s", name, project)

    def log(self, values: dict[str, Any], step: int | None = None) -> None:
        """Record one row of metrics."""
        with self._metrics.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({**values, **({"step": step} if step is not None else {})},
                                    ensure_ascii=False) + "\n")
        if self._wandb is not None:
            self._wandb.log(values, step=step)

    def summary(self, values: dict[str, Any]) -> None:
        """Record final numbers, the ones a run is compared on."""
        (self.run_dir / "summary.json").write_text(
            json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        run = getattr(self._wandb, "run", None) if self._wandb is not None else None
        if run is not None:
            run.summary.update(values)

    def finish(self) -> None:
        """Close the wandb run so the dashboard stops showing it as live."""
        if self._wandb is not None:
            try:
                self._wandb.finish()
            except Exception:                            # already closed by ultralytics
                pass
