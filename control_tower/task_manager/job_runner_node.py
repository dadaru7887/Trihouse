"""Runnable process that advances queued Jobs into dispatched steps.

This is the missing runner in the P0 chain. `POST /api/v1/orders` persists a Job
and its steps; `rmf_gateway_worker_node` carries dispatched steps to RMF. Nothing
joined the two, so `integration_messages` stayed empty and no robot ever moved.

It runs as a ROS node purely for observability: the process talks to the Gateway
over HTTP only, but appearing in `ros2 node list` lets `control_stack doctor`
report it alongside the rest of the host ROS layer. The sequencing logic itself
lives in `job_runner.py` and has no ROS or database dependency.
"""

from __future__ import annotations

import argparse
import os
import time
from typing import Callable, Protocol, Sequence

import rclpy

from control_tower.gateway.fms_client import FMSGatewayHttpClient
from control_tower.process_lifecycle import ShutdownSignal

from .job_runner import DEFAULT_PACKING_DOCK_CODES, JobRunner, JobRunnerReport


class PollRunner(Protocol):
    def run_once(self, *, limit: int) -> JobRunnerReport: ...


def run_poll_loop(
    runner: PollRunner,
    node: object,
    *,
    limit: int,
    poll_interval_s: float,
    once: bool,
    keep_running: Callable[[], bool],
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Poll while ROS is alive; separated from construction for tests."""

    while keep_running():
        report = runner.run_once(limit=limit)
        logger = node.get_logger()
        if report.changed:
            logger.info(
                "job runner cycle: "
                f"assigned={list(report.assigned)} "
                f"dispatched={list(report.dispatched)} "
                f"expired={list(report.expired)}"
            )
        for blocked in report.blocked:
            # Steady-state noise for a job waiting on a busy robot, but the
            # first signal that something is stuck. Kept at warning so it is
            # visible without being an error.
            logger.warning(f"job runner blocked: {blocked}")
        for error in report.errors:
            logger.error(f"job runner error: {error}")
        if once:
            return
        sleep(poll_interval_s)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fms-base-url",
        default=os.environ.get("FMS_GATEWAY_BASE_URL", "http://127.0.0.1:8080"),
    )
    parser.add_argument("--actor", default="control-tower-job-runner")
    parser.add_argument(
        "--packing-dock",
        action="append",
        dest="packing_docks",
        help=(
            "reservable Packing Dock code; repeatable. "
            f"Defaults to {' and '.join(DEFAULT_PACKING_DOCK_CODES)}."
        ),
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--poll-interval-s", type=float, default=1.0)
    parser.add_argument("--timeout-s", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.limit <= 0 or args.poll_interval_s <= 0 or args.timeout_s <= 0:
        raise SystemExit("limit, poll interval, and timeout must be positive")
    owns_context = False
    if not rclpy.ok():
        rclpy.init()
        owns_context = True
    # 신호를 즉시 죽는 대신 걸쇠로 받는다. 진행 중인 claim 이 보고까지
    # 끝난 뒤 주기 경계에서 나가야 작업이 주인 없이 남지 않는다.
    shutdown = ShutdownSignal.installed()
    node = rclpy.create_node("trihouse_job_runner")
    try:
        gateway = FMSGatewayHttpClient(args.fms_base_url, timeout=args.timeout_s)
        runner = JobRunner(
            gateway,
            actor=args.actor,
            packing_dock_codes=tuple(args.packing_docks or DEFAULT_PACKING_DOCK_CODES),
        )
        run_poll_loop(
            runner,
            node,
            limit=args.limit,
            poll_interval_s=args.poll_interval_s,
            once=args.once,
            keep_running=shutdown.keep_running_with(rclpy.ok),
            sleep=shutdown.sleep,
        )
        return 0
    except KeyboardInterrupt:
        return 130
    finally:
        node.destroy_node()
        if owns_context and rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
