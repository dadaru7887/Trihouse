"""Production entrypoint for inference-side recovery delivery.

This process never trains or writes MySQL. Candidate execution remains gated by
operator approval and the robot-side Safety Supervisor.
"""

from __future__ import annotations

import argparse
import os
from typing import Sequence

from vision_ai.robot.safety.config import parse_boolean, resolve_safety_gate
from vision_ai.robot.recovery.live_runtime import run_live_inference


def parse_runtime_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trihouse 5080 recovery inference runtime")
    parser.add_argument(
        "--runtime-mode",
        choices=("physical", "simulation", "training_exploration"),
        default=os.environ.get("VLM_RL_RUNTIME_MODE", "physical"),
    )
    parser.add_argument(
        "--safety-gate-enabled",
        type=parse_boolean,
        default=None,
        metavar="true|false",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_runtime_args(argv)
    safety_gate_enabled = resolve_safety_gate(
        args.runtime_mode,
        args.safety_gate_enabled,
        os.environ,
    )
    if os.environ.get("VLM_RL_EXECUTION_MODE") != "operator_approved":
        raise RuntimeError("physical recovery inference requires operator_approved mode")
    # EN: This metadata must travel with later proposals/transitions.
    # KO: 이 값은 이후 proposal/transition 메타데이터에 함께 기록해야 한다.
    os.environ["VLM_RL_EFFECTIVE_SAFETY_GATE_ENABLED"] = str(safety_gate_enabled).lower()
    run_live_inference(safety_gate_enabled=safety_gate_enabled)


if __name__ == "__main__":
    main()
