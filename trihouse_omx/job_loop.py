#!/usr/bin/env python3
"""주문이 들어오면 사람 개입 없이 pick+place까지 자동으로 도는 폴링 서비스.

지금까지 deliver.py는 사람이 터미널에서 --order로 주문을 직접 넣어야 하는 CLI
도구였다. 이 파일은 그 대신 실제 Gateway를 반복 폴링해서, "omx" 채널에 새 작업이
뜨는 순간 자동으로 집어다 실행한다 — 사람이 --order를 칠 필요가 없어진다.

control_tower/gateway/fms_client.py의 FMSGatewayHttpClient를 그대로 재사용한다
(stdlib urllib만 쓰는 순수 HTTP 클라이언트라 lerobot venv에서도 문제없이
import된다). 이건 control_tower/task_manager/executor_worker_node.py의 ROS2
폴링 루프와는 다른, 독립된 구현이다 — 그쪽은 OmxProtocolSimulator라는 가짜
로봇팔(즉시 성공 반환)을 돌리는 P0 시뮬레이션 전용이라, 여기서 검증된 파지/해제
디바운스·release 후 settle·fail-closed 중단 같은 하드웨어 안전 로직이 전혀 없다.
실제 배치에서는 그 ROS2 시뮬레이션 스택 자체를 안 띄우므로(운영 규칙), 이 파일과
경합할 일이 없다 — 코드로 막는 별도 가드는 두지 않았다.

claim → 실행 → 보고는 하나의 단위다(control_tower/process_lifecycle.py의
ShutdownSignal이 이미 이 원칙으로 설계돼 있어 그대로 재사용) — SIGINT/SIGTERM이
와도 진행 중인 사이클은 끝까지 마치고 다음 사이클 시작 전에 멈춘다.

핑키 도착은 dispatch가 이미 걸러줬을 수도 있지만, 이 파일에서 한 번 더
독립적으로 확인한다(GET /api/v1/jobs/{job_id}로 mobile 스텝의 state를 폴링) —
docs/architecture/robot_arm_safety.md의 "Pinky 도착 확인 전에 handover zone을
활성화하지 않는다"를 지키는 defense-in-depth다.

**아직 팀원에게 확인 전인 값(placeholder)** — 실제 값이 나오면 아래 함수/상수
내부만 고치면 된다, 나머지 로직은 안 바뀐다:
  - ARM_ACTION_TYPE: pick+place를 트리거하는 실제 action_type 문자열.
  - _extract_zone(): dispatch.payload["input"]에서 창고 구역을 읽는 필드명.
  - _extract_product_code(): 수량 필드가 아직 안 보여서, 지금은 dispatch 하나를
    아이템 하나·수량 1로 취급한다(과소 추정이 과다 추정보다 안전).
이 값들이 확정되기 전까지는 zone/product_code를 확정할 수 없는 dispatch를
fail-closed로(성공 처리 안 하고 실패 보고) 처리한다.

deliver.py의 run_order()를 그대로 재사용한다(subprocess로 쉘아웃하지 않음 —
RobotSession의 "로봇·카메라를 한 번만 연결" 이점을 잃지 않기 위해). v1은
출고(deliver)만 다룬다 — store.py 카탈로그가 아직 비어 있어 입고 연동은 지금
연결해도 테스트 불가능한 죽은 코드가 된다.

카메라: camera_relay.py가 실물 wrist 카메라를 독점하고 있을 때는 --wrist-cam으로
가상장치(예: /dev/video10)를 가리켜야 한다 — deliver.py를 실물로 테스트할 때와
동일하다. run_all.py가 이 순서를 관리한다.

실행 전: source ~/venv/il/bin/activate
실행 예 (상시 폴링):
    python3 job_loop.py --zone frozen --port /dev/ttyACM0 --wrist-cam /dev/video10 \\
        --gateway-url http://<gateway-host>:<port>
실행 예 (한 사이클만 보고 종료, 디버깅/테스트용):
    python3 job_loop.py --zone frozen --port /dev/ttyACM0 --wrist-cam /dev/video10 \\
        --gateway-url http://127.0.0.1:8080 --once
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# control_tower.gateway.fms_client / control_tower.process_lifecycle를 그대로
# 재사용하기 위해 저장소 루트를 sys.path에 추가한다 — stream_wrist_camera.py가
# vision_system.stream_hub.ingress를 재사용할 때와 같은 패턴. 코드는 안 건드리고
# import만 한다.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from control_tower.gateway.fms_client import (  # noqa: E402
    ExecutorDispatch,
    ExecutorDispatchClaimRequest,
    FMSGatewayHttpClient,
)
from control_tower.process_lifecycle import ShutdownSignal  # noqa: E402

import bench  # noqa: E402
import camera_config  # noqa: E402
import deliver  # noqa: E402
import mock_inputs  # noqa: E402
import outcome_report  # noqa: E402
import policy_runtime  # noqa: E402
import robot_session  # noqa: E402

WORKER_ID = "trihouse-omx-job-loop"

# "pinky" 채널은 건드리지 않는다 — cargo 센서 관측 등 이 프로세스가 만들 수
# 없는 데이터가 필요하고, 그건 우리 책임이 아니다.
CHANNELS = ("omx",)

# 물리 pick+place 한 사이클이 30~60초 걸리므로, 배치로 여러 개 쥐고 있지 않고
# 하나 끝내고 다음을 본다.
CLAIM_LIMIT = 1

DEFAULT_POLL_INTERVAL_S = 1.0  # executor_worker_node.py의 기본값과 동일

# 팀원에게 실제 값 확인 전 placeholder. 확정되면 이 한 줄만 고치면 된다.
ARM_ACTION_TYPE = "pick"

PINKY_ARRIVAL_TIMEOUT_S = deliver.PINKY_ARRIVAL_TIMEOUT_S
PINKY_POLL_INTERVAL_S = deliver.PINKY_POLL_INTERVAL_S


def _extract_zone(dispatch: ExecutorDispatch) -> str | None:
    """dispatch에서 창고 구역을 뽑는다.

    실제 필드명이 아직 확정되지 않았다(팀원이 payload 스키마를 만드는 중).
    확정되면 이 함수 내부만 고치면 되고, 호출부(_handle_dispatch)는 안 바뀐다.
    확인 가능한 값이 없거나 알려진 zone이 아니면 None — fail-closed 판단은
    호출부가 한다.
    """
    step_input = dispatch.payload.get("input") or {}
    zone = step_input.get("zone") or step_input.get("temperature_zone")
    return zone if zone in deliver.KNOWN_ZONES else None


def _extract_product_code(dispatch: ExecutorDispatch) -> str | None:
    """dispatch에서 상품 코드를 뽑는다.

    executor_worker.py의 _expected_items()와 같은 필드(expected_items/items/
    sku/product_code)를 본다. 여러 개가 올 수도 있지만, 수량·복수 아이템 처리가
    아직 확정 안 돼서 지금은 첫 번째 하나만, 수량은 항상 1로 취급한다
    (mock_inputs.MockOrderItem 생성 지점 참고) — 과소 추정이 과다 추정보다 안전.
    """
    step_input = dispatch.payload.get("input") or {}
    items = step_input.get("expected_items") or step_input.get("items")
    if isinstance(items, (list, tuple)) and items:
        return str(items[0])
    sku = step_input.get("sku") or step_input.get("product_code")
    return str(sku) if sku else None


def _pinky_arrived(
    gateway: FMSGatewayHttpClient, job_id: int, *, timeout_s: float, poll_interval_s: float
) -> bool:
    """실제 Gateway 기준 핑키 도착 재확인.

    robot_arm_safety.md "Pinky 도착 확인 전에 handover zone을 활성화하지
    않는다"를 지키는 자리다. dispatch가 이미 걸러줬을 수 있어도 여기서
    독립적으로 한 번 더 확인한다(defense-in-depth). 전용 필드가 없어서(조사
    완료 — mock_inputs.py의 기존 조사와 일치), executor_type == "mobile"인
    스텝의 state == "succeeded"를 대리 신호로 쓴다.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        job = gateway.get_job(job_id)
        if job is not None:
            for step in job.steps:
                if step.executor_type == "mobile" and step.state == "succeeded":
                    return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_interval_s)


def _report_failure(gateway: FMSGatewayHttpClient, dispatch: ExecutorDispatch, *, reason_code: str, detail: str) -> None:
    outcome_report.report_outcome(
        outcome_report.StepOutcome(
            job_step_id=dispatch.job_step_id,
            outcome="failed",
            assignment_revision=dispatch.assignment_revision,
            method_code="OMX_JOB_LOOP",
            actor_device_id=dispatch.assigned_device_id or "OMX_01",
            reason_code=reason_code,
            detail=detail,
        ),
        gateway=gateway,
        worker_id=WORKER_ID,
    )
    print(f"[job_loop] step {dispatch.job_step_id}: {reason_code} — {detail}")


def _handle_dispatch(
    gateway: FMSGatewayHttpClient,
    dispatch: ExecutorDispatch,
    connected_robot,
    dataset_features: dict,
    bench_: bench.Bench,
    *,
    zone: str,
    episode_steps: int,
    fps: float,
    debug_gripper: bool,
) -> None:
    if dispatch.executor_type != "arm" or dispatch.action_type != ARM_ACTION_TYPE:
        print(
            f"[job_loop] step {dispatch.job_step_id}: executor_type={dispatch.executor_type!r} "
            f"action_type={dispatch.action_type!r} — 모르는 조합, 건너뜀 (조용히 성공 처리 안 함)"
        )
        return

    dispatch_zone = _extract_zone(dispatch)
    if dispatch_zone is None:
        _report_failure(
            gateway, dispatch, reason_code="ZONE_UNCONFIRMED",
            detail="dispatch payload에서 zone을 확정할 수 없음 (필드 미확정 — job_loop.py의 _extract_zone 참고)",
        )
        return
    if dispatch_zone != zone:
        _report_failure(
            gateway, dispatch, reason_code="ZONE_MISMATCH",
            detail=f"dispatch zone={dispatch_zone!r}, 이 워커는 --zone {zone!r}만 처리",
        )
        return

    product_code = _extract_product_code(dispatch)
    if product_code is None:
        _report_failure(
            gateway, dispatch, reason_code="PRODUCT_CODE_UNCONFIRMED",
            detail="dispatch payload에서 product_code를 확정할 수 없음",
        )
        return

    arrived = _pinky_arrived(
        gateway, dispatch.job_id, timeout_s=PINKY_ARRIVAL_TIMEOUT_S, poll_interval_s=PINKY_POLL_INTERVAL_S
    )
    if not arrived:
        _report_failure(
            gateway, dispatch, reason_code="PINKY_NOT_ARRIVED",
            detail="fail-closed: handover zone not activated before pinky arrival",
        )
        return

    order = mock_inputs.MockOrder(
        order_id=f"job-loop-step-{dispatch.job_step_id}",
        job_step_id=dispatch.job_step_id,
        assignment_revision=dispatch.assignment_revision,
        items=(mock_inputs.MockOrderItem(1, product_code, 1),),
        # 위에서 이미 실제 Gateway로 도착을 확인했으니, run_order 내부의
        # (mock 기반) 재확인은 즉시 통과하면 된다.
        pinky=mock_inputs.MockPinkyArrival(already_arrived=True),
    )

    deliver.run_order(
        connected_robot,
        dataset_features,
        order,
        zone=zone,
        episode_steps=episode_steps,
        fps=fps,
        bench_=bench_,
        debug_gripper=debug_gripper,
        is_first_order=False,
        gateway=gateway,
        worker_id=WORKER_ID,
    )


def _run_cycle(
    gateway: FMSGatewayHttpClient,
    connected_robot,
    dataset_features: dict,
    bench_: bench.Bench,
    *,
    zone: str,
    episode_steps: int,
    fps: float,
    debug_gripper: bool,
) -> bool:
    """한 사이클: dispatch 최대 하나 클레임 → 처리. 클레임된 게 있었으면 True."""
    dispatches = gateway.claim_executor_dispatches(
        ExecutorDispatchClaimRequest(worker_id=WORKER_ID, channels=CHANNELS, limit=CLAIM_LIMIT)
    )
    if not dispatches:
        return False
    _handle_dispatch(
        gateway,
        dispatches[0],
        connected_robot,
        dataset_features,
        bench_,
        zone=zone,
        episode_steps=episode_steps,
        fps=fps,
        debug_gripper=debug_gripper,
    )
    return True


def run_poll_loop(
    gateway: FMSGatewayHttpClient,
    connected_robot,
    dataset_features: dict,
    bench_: bench.Bench,
    *,
    zone: str,
    episode_steps: int,
    fps: float,
    debug_gripper: bool,
    poll_interval_s: float,
    once: bool,
    shutdown: ShutdownSignal,
) -> None:
    """executor_worker_node.py의 run_poll_loop와 같은 철학.

    사이클 하나가 실패해도(예: Gateway가 재배포되며 순간적으로 연결이 끊김)
    로그만 남기고 계속 돈다 — 프로세스를 죽이지 않는다. "사이클 하나 잃는 게
    프로세스 잃는 것보다 낫다"(원본 주석 그대로의 이유: 사람이 알아채기까지
    시간이 걸린다).
    """
    while not shutdown.requested:
        try:
            _run_cycle(
                gateway,
                connected_robot,
                dataset_features,
                bench_,
                zone=zone,
                episode_steps=episode_steps,
                fps=fps,
                debug_gripper=debug_gripper,
            )
        except Exception as error:  # noqa: BLE001
            print(f"[job_loop] cycle failed: {error}")
            if once:
                return
            shutdown.sleep(poll_interval_s)
            continue
        if once:
            return
        shutdown.sleep(poll_interval_s)


def _resolve_camera_ports(args: argparse.Namespace) -> tuple[str, str]:
    """--front-cam/--wrist-cam이 주어지면 그대로, 아니면 set_cameras.py로 저장해둔 값을 쓴다.

    camera_relay.py를 경유하는 상시 실행 구성에서는 --wrist-cam이 실물이 아니라
    가상장치(예: /dev/video10)를 가리켜야 한다 — deliver.py를 실물로 테스트할
    때와 동일한 주의사항.
    """
    if args.front_cam and args.wrist_cam:
        return args.front_cam, args.wrist_cam
    saved = camera_config.load()
    if saved is None:
        raise SystemExit(
            "카메라 포트를 모른다: --front-cam/--wrist-cam을 직접 주거나, "
            "먼저 `python3 set_cameras.py --front /dev/videoN --wrist /dev/videoM`로 저장해둘 것."
        )
    front = args.front_cam or saved.front
    wrist = args.wrist_cam or saved.wrist
    print(f"[camera] using saved ports (run set_cameras.py to change): front={front} wrist={wrist}")
    return front, wrist


def run(args: argparse.Namespace) -> None:
    front_cam, wrist_cam = _resolve_camera_ports(args)
    robot = robot_session.build_robot(
        port=args.port,
        cameras=(
            robot_session.CameraSpec("front", front_cam, width=args.cam_width, height=args.cam_height, fps=args.cam_fps),
            robot_session.CameraSpec("wrist", wrist_cam, width=args.cam_width, height=args.cam_height, fps=args.cam_fps),
        ),
    )
    gateway = FMSGatewayHttpClient(args.gateway_url)
    bench_ = bench.Bench()
    shutdown = ShutdownSignal.installed()

    with robot_session.RobotSession(robot) as connected_robot:
        dataset_features = policy_runtime.build_dataset_features(connected_robot)
        run_poll_loop(
            gateway,
            connected_robot,
            dataset_features,
            bench_,
            zone=args.zone,
            episode_steps=args.episode_steps,
            fps=args.fps,
            debug_gripper=args.debug_gripper,
            poll_interval_s=args.poll_interval_s,
            once=args.once,
            shutdown=shutdown,
        )

    print("\n" + bench_.summary())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", required=True, help="OMX follower serial port, e.g. /dev/ttyACM0")
    parser.add_argument(
        "--zone", required=True, choices=deliver.KNOWN_ZONES,
        help="이 워커가 처리할 창고 구역. dispatch의 zone과 다르면 ZONE_MISMATCH로 거절한다.",
    )
    parser.add_argument(
        "--gateway-url", required=True,
        help="FMS Gateway base URL, 예: http://127.0.0.1:8080 (control_tower.gateway.fms_client.FMSGatewayHttpClient에 그대로 넘김)",
    )
    parser.add_argument(
        "--poll-interval-s", type=float, default=DEFAULT_POLL_INTERVAL_S,
        help=f"클레임 폴링 주기(초). 기본 {DEFAULT_POLL_INTERVAL_S} (executor_worker_node.py 기본값과 동일).",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="한 사이클만 돌고 종료 (디버깅/테스트용 — 무한 루프를 계속 안 켜놔도 됨).",
    )
    parser.add_argument(
        "--front-cam", default=None,
        help="front camera, e.g. /dev/video4 (권장: 전체 경로). 생략하면 set_cameras.py로 저장해둔 값을 씀.",
    )
    parser.add_argument(
        "--wrist-cam", default=None,
        help="wrist camera. camera_relay.py 경유 구성에서는 가상장치(예: /dev/video10)를 가리킬 것. "
             "생략하면 set_cameras.py로 저장해둔 값을 씀(실물 카메라 — camera_relay.py 없이 단독 테스트할 때만).",
    )
    parser.add_argument(
        "--episode-steps", type=int, default=900,
        help="정책 최대 실행 스텝 수(안전 상한). deliver.py와 동일한 기본값·이유.",
    )
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument("--cam-width", type=int, default=640)
    parser.add_argument("--cam-height", type=int, default=480)
    parser.add_argument("--cam-fps", type=int, default=30)
    parser.add_argument(
        "--debug-gripper", action="store_true",
        help="매 스텝마다 그리퍼 Present_Current/Present_Position을 콘솔에 실시간 출력.",
    )
    return parser


if __name__ == "__main__":
    run(_parser().parse_args())
