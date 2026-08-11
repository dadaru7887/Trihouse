"""Open-RMF 에너지 bridge를 수동 검증하는 JSON 출력 CLI."""

import argparse
from dataclasses import asdict
import json
from typing import Sequence

import rclpy

from .energy_estimator import EstimateRequest, EstimateService
from .ros_energy_client import RosEstimateService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robot-id", default="tinyRobot1")
    parser.add_argument("--task-id", default="manual-energy-test")
    parser.add_argument("--map-revision", default="office")
    parser.add_argument("--waypoint", action="append", required=True)
    parser.add_argument("--current-soc", type=float, default=1.0)
    parser.add_argument("--loading-duration-s", type=float, default=30.0)
    parser.add_argument("--handover-duration-s", type=float, default=30.0)
    parser.add_argument("--buffer-duration-s", type=float, default=15.0)
    parser.add_argument("--timeout-s", type=float, default=2.0)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    service: EstimateService | None = None,
) -> int:
    args = _parser().parse_args(argv)
    request = EstimateRequest(
        robot_id=args.robot_id,
        task_id=args.task_id,
        map_revision=args.map_revision,
        waypoint_ids=tuple(args.waypoint),
        current_state_of_charge=args.current_soc,
        expected_loading_duration_s=args.loading_duration_s,
        expected_handover_duration_s=args.handover_duration_s,
        task_time_buffer_s=args.buffer_duration_s,
    )

    node = None
    owns_context = False
    if service is None:
        if not rclpy.ok():
            rclpy.init()
            owns_context = True
        node = rclpy.create_node("trihouse_estimate_energy_cli")
        service = RosEstimateService(node)

    try:
        response = service(request, args.timeout_s)
        print(json.dumps(asdict(response), ensure_ascii=False, sort_keys=True))
        return 0 if response.success else 1
    finally:
        if node is not None:
            node.destroy_node()
        if owns_context and rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
