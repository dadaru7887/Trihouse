"""Runnable ROS process that bridges FMS RMF dispatches to the RMF task API."""

from __future__ import annotations

import argparse
import os
import time
from typing import Any, Callable, Protocol, Sequence

import rclpy
from rclpy.parameter import Parameter

from control_tower.gateway.fms_client import (
    FMSGatewayHttpClient,
    RmfTaskUpdateRequest,
)
from control_tower.process_lifecycle import ShutdownSignal

from .rmf_gateway_worker import RmfGatewayWorker, RmfGatewayWorkerReport
from .ros_task_client import (
    RosFleetStateObserver,
    RosTaskApiClient,
    RosTaskSummaryObserver,
)


class PollWorker(Protocol):
    def run_once(self, *, limit: int) -> RmfGatewayWorkerReport: ...


class GatewayTaskUpdateSink:
    """관측한 RMF task 갱신을 HTTP 로만 원장에 넘긴다.

    Control Tower 는 DB 에 직접 붙지 않는다 — "DB 트랜잭션은 Gateway 만" 이
    설계 경계다. `RosTaskSummaryObserver` 가 요구하는 두 메서드를 그 경계
    안에서 채운다.

    아는 task 인지는 Gateway 가 판단한다. TaskSummary 는 fleet 전체의 것이
    오므로 여기서 미리 거르려면 task 목록을 따로 들고 있어야 하고, 그러면
    같은 사실이 두 곳에 생긴다. 대신 Gateway 가 모르는 task 에 404 를 주고
    클라이언트가 그것을 `None` 으로 돌려준다.
    """

    def __init__(self, gateway: FMSGatewayHttpClient) -> None:
        self._gateway = gateway

    def knows_task(self, task_id: str) -> bool:
        return bool(task_id.strip())

    def apply_task_update(self, update: Any) -> bool:
        applied = self._gateway.apply_rmf_task_update(
            RmfTaskUpdateRequest(
                rmf_task_id=update.task_id,
                fleet_name=update.fleet_name,
                robot_name=update.robot_name,
                rmf_status=update.rmf_status,
                step_state=update.step_state,
                observed_at_ms=update.observed_at_ms,
                detail=update.detail,
            )
        )
        return applied is not None


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
    parser.add_argument("--task-summary-topic", default="task_summaries")
    parser.add_argument("--fleet-state-topic", default="fleet_states")
    parser.add_argument("--once", action="store_true")
    # 시뮬에서는 RMF fleet adapter 가 use_sim_time 으로 돈다. 워커가 벽시계로
    # 남으면 시작 시각이 수십 년 어긋나 작업이 시작되지 않는다. 실기에서는
    # 주지 않는다 — 그쪽은 두 시계가 원래 같다.
    parser.add_argument("--use-sim-time", action="store_true")
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
    if args.use_sim_time:
        node.set_parameters([Parameter("use_sim_time", value=True)])
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
            # RMF 와 같은 시계로 시작 시각을 찍는다. 이 노드가 use_sim_time 이면
            # 시뮬 시계가, 실기면 벽시계가 그대로 온다. 원장의 created_at 을
            # 쓰면 시뮬에서 두 시계가 수십 년 어긋나 작업이 시작되지 않는다.
            now_ms=lambda: node.get_clock().now().nanoseconds // 1_000_000,
        )
        # RMF 는 제출 즉시 booking 만 만들고 배정은 입찰이 끝난 뒤에 정해진다.
        # 이 관측자가 없으면 그 배정이 원장에 닿지 못해 dispatch 가
        # RMF_ASSIGNMENT_PENDING 에서 재시도를 소진하고 dead_letter 가 된다.
        sink = GatewayTaskUpdateSink(gateway)
        # 두 창구를 함께 연다. `task_summaries` 는 이 RMF 배포에서 비어 있지만
        # (2026-08-19 실측 12초 0건) 다른 배포에서는 흐르므로 남겨 둔다. 실제로
        # 배정을 물어다 주는 것은 `fleet_states` 다 — 같은 12초에 97건이 왔다.
        # 이것이 없으면 dispatch 가 RMF_ASSIGNMENT_PENDING 으로 재시도를 소진해
        # dead_letter 가 되고, RMF 와 로봇은 정상인데 원장만 실패로 남는다.
        summary_observer = RosTaskSummaryObserver(sink)
        summary_observer.attach(node, topic=args.task_summary_topic)
        fleet_observer = RosFleetStateObserver(sink)
        fleet_observer.attach(node, topic=args.fleet_state_topic)
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
