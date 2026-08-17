"""Runnable ROS process that bridges FMS RMF dispatches to the RMF task API."""

from __future__ import annotations

import argparse
import os
import time
from typing import Callable, Protocol, Sequence

import rclpy

from control_tower.gateway.fms_client import FMSGatewayHttpClient
from control_tower.process_lifecycle import ShutdownSignal

from .rmf_gateway_worker import RmfGatewayWorker, RmfGatewayWorkerReport
from .ros_task_client import RosTaskApiClient


class PollWorker(Protocol):
    def run_once(self, *, limit: int) -> RmfGatewayWorkerReport: ...


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
    """Poll while ROS is alive; separated from construction for deterministic tests."""

    while keep_running():
        try:
            report = worker.run_once(limit=limit)
        except Exception as error:  # noqa: BLE001
            # 한 주기의 실패로 프로세스가 죽으면 dispatch 가 통째로 멈추고 로봇이
            # 조용히 선다. 실제로 취소된 step 을 가리키는 outbox 메시지 하나가
            # Gateway 에서 409 를 받아 이 loop 를 끝냈고, 그 사실은 로그를 뒤져야
            # 보였다. 다음 주기가 다시 시도하고, 영구적인 실패라면 같은 줄이
            # 반복되어 눈에 띈다.
            node.get_logger().error(f"RMF dispatch cycle failed: {error}")
        else:
            node.get_logger().info(
                "RMF dispatch cycle: "
                f"claimed={report.claimed} accepted={report.accepted} "
                f"rejected={report.rejected} indeterminate={report.indeterminate}"
            )
        if once:
            return
        sleep(poll_interval_s)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fms-base-url",
        default=os.environ.get("FMS_GATEWAY_BASE_URL", "http://127.0.0.1:8080"),
    )
    parser.add_argument("--worker-id", default="control-tower-rmf-worker")
    parser.add_argument("--fleet-name", default="project1_pinky")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--poll-interval-s", type=float, default=1.0)
    parser.add_argument("--timeout-s", type=float, default=5.0)
    parser.add_argument("--request-topic", default="task_api_requests")
    parser.add_argument("--response-topic", default="task_api_responses")
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
    node = rclpy.create_node("trihouse_rmf_gateway_worker")
    try:
        gateway = FMSGatewayHttpClient(args.fms_base_url, timeout=args.timeout_s)
        transport = RosTaskApiClient(
            node,
            request_topic=args.request_topic,
            response_topic=args.response_topic,
        )
        worker = RmfGatewayWorker(
            gateway,
            transport,
            worker_id=args.worker_id,
            default_fleet_name=args.fleet_name,
            timeout_s=args.timeout_s,
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
