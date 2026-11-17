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
    # `auto_bounded` 는 승인을 없애는 것이 아니라 **누가 승인하는가**를 넓힌다.
    # Gateway 의 tier 규칙이 제한된 제안만 자동 승인하고, 나머지는 그대로 사람에게
    # 간다. 실행 직전 경로 검사·로봇 admission·safety supervisor 는 두 모드에서
    # 동일하게 동작한다. 알 수 없는 모드는 거부한다 — 오타가 무단 자율 주행이
    # 되어서는 안 된다.
    execution_mode = os.environ.get("VLM_RL_EXECUTION_MODE")
    if execution_mode not in {"operator_approved", "auto_bounded"}:
        raise RuntimeError(
            "physical recovery inference requires operator_approved or auto_bounded mode"
        )
    # EN: This metadata must travel with later proposals/transitions.
    # KO: 이 값은 이후 proposal/transition 메타데이터에 함께 기록해야 한다.
    os.environ["VLM_RL_EFFECTIVE_SAFETY_GATE_ENABLED"] = str(safety_gate_enabled).lower()
    run_live_inference(safety_gate_enabled=safety_gate_enabled)


if __name__ == "__main__":
    main()
