"""OMX 프로토콜 시뮬레이터 프로세스.

`--omx-id OMX_01`, `--omx-id OMX_02`로 두 인스턴스를 띄운다. 각 프로세스는
Gateway가 보낸 prepare/load/hold/reset 명령을 NDJSON으로 stdin에서 읽고
결정적인 상태 전이 이벤트를 stdout으로 낸다. 물리 OMX ROS endpoint는
흉내내지 않으며 실제 motion은 절대 나가지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import IO

from .act_policy import ActPolicyLoader
from .protocol_simulator import OmxProtocolSimulator, OmxSimulatorError


DEFAULT_ACT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "act.simulation.yaml"


def run(
    simulator: OmxProtocolSimulator,
    *,
    source: IO[str],
    sink: IO[str],
    act_config: Path = DEFAULT_ACT_CONFIG,
) -> int:
    """한 줄에 한 명령을 읽어 이벤트 줄들을 낸다."""
    policy = ActPolicyLoader().load_file(act_config)
    if policy.real_motion_enabled:
        raise RuntimeError(
            "P0 simulation must never load a policy that enables real OMX motion"
        )

    for line in source:
        if not line.strip():
            continue
        try:
            command = json.loads(line)
        except json.JSONDecodeError as error:
            _emit(sink, {"error": "INVALID_JSON", "detail": str(error)})
            continue
        try:
            events = simulator.execute(command)
        except OmxSimulatorError as error:
            _emit(sink, {"error": str(error).split(":", 1)[0], "detail": str(error)})
            continue
        episode = policy.run_episode(
            command_uuid=command["command_uuid"],
            assignment_revision=command["assignment_revision"],
        )
        for event in events:
            _emit(
                sink,
                {
                    **asdict(event),
                    "expected_items": list(event.expected_items),
                    "model_lineage": episode.model_lineage,
                    "act_stages": [stage.name for stage in episode.stages],
                    "real_motion_emitted": episode.real_motion_emitted,
                },
            )
    return 0


def _emit(sink: IO[str], payload: dict) -> None:
    sink.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sink.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--omx-id", required=True, choices=("OMX_01", "OMX_02"))
    parser.add_argument("--act-config", type=Path, default=DEFAULT_ACT_CONFIG)
    args = parser.parse_args(argv)
    return run(
        OmxProtocolSimulator(omx_id=args.omx_id),
        source=sys.stdin,
        sink=sys.stdout,
        act_config=args.act_config,
    )


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
