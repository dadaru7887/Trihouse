"""Runnable process that executes OMX/FMS steps and reports their outcome.

Pairs with `job_runner_node`: the runner dispatches the current step, this
process executes the non-mobile ones and closes them, which opens the next step
for the runner. Without it an order stops at its first `pick` and no navigation
is ever dispatched.

It runs as a ROS node for observability only — all Gateway traffic is HTTP — so
that `control_stack doctor` can report it beside the rest of the host ROS layer.
The sequencing logic lives in `executor_worker.py` with no ROS or database
dependency.
"""

from __future__ import annotations

import argparse
import os
import time
from typing import Callable, Protocol, Sequence

import rclpy

from control_tower.gateway.fms_client import FMSGatewayHttpClient
from control_tower.process_lifecycle import ShutdownSignal

from .executor_worker import ExecutorReport, ExecutorWorker


DEFAULT_OMX_IDS = ("OMX_01", "OMX_02")


class PollWorker(Protocol):
    def run_once(self, *, limit: int) -> ExecutorReport: ...


def run_poll_loop(
    worker: PollWorker,
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
        report = worker.run_once(limit=limit)
        logger = node.get_logger()
        if report.changed:
            logger.info(
                "executor cycle: "
                f"claimed={report.claimed} "
                f"succeeded={list(report.succeeded)} failed={list(report.failed)}"
            )
        for deferred in report.deferred:
            logger.info(f"executor deferred: {deferred}")
        for error in report.errors:
            logger.error(f"executor error: {error}")
        if once:
            return
        sleep(poll_interval_s)


def _build_simulators(omx_ids: Sequence[str], act_config: str | None):
    """Load the arm contract simulators, refusing anything that moves hardware."""
    from trihouse_omx_adapter.act_policy import ActPolicyLoader
    from trihouse_omx_adapter.protocol_simulator import OmxProtocolSimulator

    if act_config:
        policy = ActPolicyLoader().load_file(act_config)
        if policy.real_motion_enabled:
            raise SystemExit(
                "P0 simulation must never load a policy that enables real OMX motion"
            )
    return {omx_id: OmxProtocolSimulator(omx_id=omx_id) for omx_id in omx_ids}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fms-base-url",
        default=os.environ.get("FMS_GATEWAY_BASE_URL", "http://127.0.0.1:8080"),
    )
    parser.add_argument("--worker-id", default="control-tower-executor")
    parser.add_argument(
        "--omx-id",
        action="append",
        dest="omx_ids",
        help=f"arm to simulate; repeatable. Defaults to {' and '.join(DEFAULT_OMX_IDS)}.",
    )
    parser.add_argument(
        "--act-config",
        default=os.environ.get("TRIHOUSE_ACT_CONFIG", ""),
        help="ACT policy file; refuses to start if it enables real motion",
    )
    parser.add_argument(
        "--environment",
        default=os.environ.get("TRIHOUSE_ENVIRONMENT", "simulation"),
        choices=("simulation", "hardware"),
        help="tags every duration sample so simulated runs never calibrate hardware",
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
    node = rclpy.create_node("trihouse_executor_worker")
    try:
        gateway = FMSGatewayHttpClient(args.fms_base_url, timeout=args.timeout_s)
        worker = ExecutorWorker(
            gateway,
            simulators=_build_simulators(
                tuple(args.omx_ids or DEFAULT_OMX_IDS), args.act_config or None
            ),
            worker_id=args.worker_id,
            environment=args.environment,
        )
        run_poll_loop(
            worker,
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
