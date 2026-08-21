#!/usr/bin/env python3
"""출고(deliver) — 로봇팔이 선반에서 상품을 집어 핑키 바구니로 옮긴다.

--zone {frozen,chilled,ambient}로 창고 구역을 고른다. 하드웨어·세이프티·CLI
골격은 세 구역 다 동일하고, policy_catalog 조회에 --zone 값을 그대로 넘겨서
다른 구역 품목을 실수로 집으러 가지 않게 fail-closed 한다(예: --zone chilled로
dumpling(냉동 품목)을 주문하면 zone 불일치로 거절). 냉장/상온은 아직 학습된
정책이 하나도 없어서(policy_catalog.py 참고) --zone chilled/ambient는 지금은
항상 UnknownProductError로 끝난다 — 의도된 동작이다.

1단계 목표 (실제 관제 연동 전, trihouse_omx/ 안에서만 검증):
  - 3·4번 인터페이스(상품 정보, 핑키 도착 상태값)를 mock_inputs.py로 임의 공급했을 때
    로봇이 정상 동작하는지 확인한다.
  - 로봇·카메라를 프로세스 시작 시 한 번만 연결하고, 물품이 바뀔 때마다 정책만
    교체했을 때 지연시간이 실제로 줄어드는지 bench.py로 실측한다.
  - 그리퍼 전류 기반 파지 판정(grasp_check)이 동작하는지 확인한다.

1·2번 인터페이스(완료 상태, QR 영상)는 아직 실제 관제로 나가지 않는다.
outcome_report는 로컬 JSONL 스텁이고, QR 영상 송출(RTSP)은 이 단계에 없다.

핑키 도착 확인 전에는 인계(그리퍼를 여는 것)로 넘어가지 않는다 — 이건
docs/architecture/robot_arm_safety.md의 금지 연결을 지키는 부분이라 mock이어도
그대로 지킨다.

실행 전: source ~/venv/il/bin/activate
실행 예:
    python3 deliver.py --zone frozen --port /dev/ttyACM0 --front-cam /dev/video0 --wrist-cam /dev/video6
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

import bench
import camera_config
import grasp_check
import mock_inputs
import outcome_report
import policy_catalog
import policy_runtime
import robot_session

KNOWN_ZONES = ("frozen", "chilled", "ambient")

PINKY_ARRIVAL_TIMEOUT_S = 10.0
PINKY_POLL_INTERVAL_S = 0.5

# 정책 초반엔 그리퍼가 아직 목표를 향해 움직이는 중이라 파지 판정이 무의미하다.
# 이 스텝 수만큼은 grasp_check를 건너뛴다.
GRASP_CHECK_START_STEP = 30

# release가 확인돼도 그 자리에서 바로 멈추지 않고 이만큼 더 정책을 실행한다.
# 학습된 에피소드는 "집고 → 놓고 → 제자리 복귀"까지가 한 세트다(사용자 확인).
# release 확인 즉시 멈추면 팔이 바구니 위 등 임의 자세로 뻗어 있는 채로 다음
# 아이템/주문으로 넘어가거나 disconnect(토크 해제)로 이어질 수 있는데, 토크가
# 꺼지면 지지되지 않은 자세에서 팔이 중력으로 그대로 무너진다 — 실제로 겪은
# 사고. 100스텝으로 실측한 결과 복귀 동작 막판에 살짝 못 미쳐 120으로 늘림
# (fps 15 기준 약 8초) — 여전히 실측하며 조정해야 하는 값이다.
POST_RELEASE_SETTLE_STEPS = 120


def _wait_for_pinky(pinky: mock_inputs.MockPinkyArrival, *, timeout_s: float) -> bool:
    """핑키 도착 상태값(4번 인터페이스, 지금은 mock)을 폴링한다.

    실제 연동 시에는 GET /api/v1/jobs/{id}로 같은 번들의 mobile/navigate 스텝
    state를 폴링하는 자리가 된다 (조사 결과: 전용 필드 없음, 이게 유일한 대리 신호).
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if pinky.has_arrived():
            return True
        time.sleep(PINKY_POLL_INTERVAL_S)
    return pinky.has_arrived()


@dataclass(frozen=True)
class ItemVerdict:
    """물체 하나의 pick+place 사이클 최종 판정.

    grasped만으로는 "바구니에 담았다"를 보장하지 못한다 — 정책이 물건을
    집은 뒤에도 계속 실행되므로, 실제로 손을 놓았는지(released)까지 확인해야
    한 아이템이 끝난 것이다. released=True일 때만 이 물체의 인계가 완료된
    것으로 본다.
    """

    grasped: bool
    released: bool
    step_grasped: int | None
    step_released: int | None
    present_current: float
    present_position: float
    reason: str


def run_item(
    robot,
    dataset_features: dict,
    item: mock_inputs.MockOrderItem,
    *,
    zone: str,
    order_id: str,
    is_first_order: bool,
    episode_steps: int,
    fps: float,
    bench_: bench.Bench,
    debug_gripper: bool = False,
) -> ItemVerdict:
    """정책 하나를 실행해 물체 하나를 pick+place한다.

    episode_steps는 pick+place 전체 사이클(제자리→집기→바구니로 이동→놓기→
    제자리 복귀)을 담을 만큼 충분히 커야 한다. 시간을 기준으로 멈추면 수량이
    2개 이상인 주문에서 첫 물건을 놓고도 시간이 남아 정책이 다음 물건을 향해
    또 움직이기 시작하는 게 실물로 확인됐다 — 그래서 파지 후 그리퍼가 다시
    열려 물건을 놓았다고 확인되는 순간(release confirmed) 바로 루프를 끝내고
    다음 아이템으로 넘어간다.
    """
    entry = policy_catalog.lookup(item.product_code, zone=zone)
    control_interval_s = 1.0 / fps

    grasp_verdict: grasp_check.GraspVerdict | None = None
    step_grasped: int | None = None
    release_verdict: grasp_check.ReleaseVerdict | None = None
    step_released: int | None = None
    settle_deadline: int | None = None
    grasp_debounce = grasp_check.Debouncer()
    release_debounce = grasp_check.Debouncer()

    with bench_.measure(order_id=order_id, product_code=item.product_code, is_first_order=is_first_order) as tick:
        loaded = policy_runtime.load_policy(entry.policy_repo_id)
        loaded.reset()
        tick("policy_loaded")

        for step in range(episode_steps):
            loop_start = time.perf_counter()
            action = policy_runtime.infer_step(robot, loaded, dataset_features, task=entry.label_ko)
            robot.send_action(action)
            if step == 0:
                tick("first_action")
            elapsed = time.perf_counter() - loop_start
            sleep_left = control_interval_s - elapsed
            if sleep_left > 0:
                time.sleep(sleep_left)

            # 스텝당 모터를 한 번만 읽어서 디버그 출력과 판정에 그대로 재사용한다
            # (따로 읽으면 몇 ms 차이로 값이 어긋날 수 있다 — 실측으로 확인됨).
            current, position = grasp_check.read_gripper(robot)
            if debug_gripper:
                print(f"[{order_id}] step={step:4d} item={item.product_code} gripper_current={current:>5} gripper_position={position:6.2f}")

            if step < GRASP_CHECK_START_STEP:
                continue

            if grasp_verdict is None:
                verdict = grasp_check.evaluate_grasp(current, position)
                if grasp_debounce.update(verdict.grasped):
                    grasp_verdict = verdict
                    step_grasped = step
                    print(f"[{order_id}] item={item.product_code} grasped at step {step} (debounced)")
            elif release_verdict is None:
                rverdict = grasp_check.evaluate_release(current, position)
                if release_debounce.update(rverdict.released):
                    release_verdict = rverdict
                    step_released = step
                    settle_deadline = step + POST_RELEASE_SETTLE_STEPS
                    print(
                        f"[{order_id}] item={item.product_code} released at step {step} (debounced) "
                        f"— settling {POST_RELEASE_SETTLE_STEPS} more steps for return-to-home before ending"
                    )
            elif step >= settle_deadline:
                print(f"[{order_id}] item={item.product_code} settle complete at step {step} — episode complete")
                break

    final_grasp = grasp_verdict if grasp_verdict is not None else grasp_check.check_grasp(robot)
    if release_verdict is not None:
        reason = "PLACE_CONFIRMED"
    elif grasp_verdict is not None:
        reason = "RELEASE_NOT_CONFIRMED"
    else:
        reason = final_grasp.reason

    return ItemVerdict(
        grasped=grasp_verdict is not None,
        released=release_verdict is not None,
        step_grasped=step_grasped,
        step_released=step_released,
        present_current=final_grasp.present_current,
        present_position=final_grasp.present_position,
        reason=reason,
    )


def run_order(
    connected_robot,
    dataset_features: dict,
    order: mock_inputs.MockOrder,
    *,
    zone: str,
    episode_steps: int,
    fps: float,
    bench_: bench.Bench,
    debug_gripper: bool = False,
    is_first_order: bool = False,
    gateway=None,
    worker_id: str = "trihouse-omx",
) -> None:
    """주문 하나(핑키 대기 → 품목별 pick+place → 완료 보고)를 끝까지 처리한다.

    job_loop.py가 실제 Gateway에서 클레임한 dispatch 하나를 이 함수 하나로
    실행할 수 있도록, CLI(argparse.Namespace)에 묶이지 않게 분리해뒀다 —
    run(args)는 이 함수를 감싸는 얇은 CLI 진입점일 뿐이다.

    gateway/worker_id는 outcome_report.report_outcome에 그대로 넘긴다 — CLI
    경로(job_loop.py를 거치지 않는 run(args))는 안 주므로 기존과 동일하게 로컬
    JSONL만 남긴다.
    """
    print(f"\n=== order {order.order_id} (job_step_id={order.job_step_id}) ===")

    arrived = _wait_for_pinky(order.pinky, timeout_s=PINKY_ARRIVAL_TIMEOUT_S)
    if not arrived:
        outcome_report.report_outcome(
            outcome_report.StepOutcome(
                job_step_id=order.job_step_id,
                outcome="failed",
                assignment_revision=order.assignment_revision,
                method_code="OMX_DELIVER_MOCK",
                actor_device_id="OMX_01",
                reason_code="PINKY_NOT_ARRIVED",
                detail="fail-closed: handover zone not activated before pinky arrival",
            ),
            gateway=gateway,
            worker_id=worker_id,
        )
        print(f"[{order.order_id}] pinky did not arrive within timeout — skipping (fail-closed)")
        return

    # reserved_quantity만큼 물리적으로 따로 집어야 한다 — 정책 한 번 실행이
    # "그 품목을 한 개 pick+place"하는 단위이므로, 수량이 2면 같은 품목을
    # 두 번 반복 실행한다(실측 확인: 수량을 넣어도 무시하고 1개만 집던 문제).
    units = [item for item in order.items for _ in range(item.reserved_quantity)]
    item_results = []
    for unit_index, item in enumerate(units):
        verdict = run_item(
            connected_robot,
            dataset_features,
            item,
            zone=zone,
            order_id=order.order_id,
            is_first_order=is_first_order and unit_index == 0,
            episode_steps=episode_steps,
            fps=fps,
            bench_=bench_,
            debug_gripper=debug_gripper,
        )
        item_results.append((item, verdict))
        print(
            f"[{order.order_id}] item={item.product_code} grasped={verdict.grasped} "
            f"released={verdict.released} step_grasped={verdict.step_grasped} "
            f"step_released={verdict.step_released} "
            f"current={verdict.present_current} position={verdict.present_position} "
            f"reason={verdict.reason}"
        )
        if not verdict.released:
            # fail-closed: 그리퍼 상태가 불확실한 채로 다음 물건을 집으러
            # 가지 않는다. 실측으로 확인된 문제 — release가 확인 안 된 채
            # 다음 아이템으로 넘어가면, 이전 물건의 잔여 그리퍼 상태(반쯤
            # 닫힘 등)를 다음 아이템의 grasp_check 시작 시점에 그대로
            # 읽어버려 "아직 집지도 않았는데 집었다"는 오탐이 난다.
            print(
                f"[{order.order_id}] item={item.product_code} release 미확인 — "
                "그리퍼 상태 불확실, 나머지 품목 중단 (fail-closed)"
            )
            break

    all_placed = all(verdict.released for _, verdict in item_results)
    any_grasped = any(verdict.grasped for _, verdict in item_results)
    if all_placed:
        reason_code = "PLACE_CONFIRMED"
    elif any_grasped:
        reason_code = "RELEASE_NOT_CONFIRMED"
    else:
        reason_code = "GRASP_NOT_CONFIRMED"
    outcome_report.report_outcome(
        outcome_report.StepOutcome(
            job_step_id=order.job_step_id,
            outcome="succeeded" if all_placed else "failed",
            assignment_revision=order.assignment_revision,
            method_code="OMX_DELIVER_MOCK",
            actor_device_id="OMX_01",
            reason_code=reason_code,
            metrics={
                "items": [
                    {
                        "product_code": item.product_code,
                        "grasped": verdict.grasped,
                        "released": verdict.released,
                        "step_grasped": verdict.step_grasped,
                        "step_released": verdict.step_released,
                        "present_current": verdict.present_current,
                        "present_position": verdict.present_position,
                    }
                    for item, verdict in item_results
                ]
            },
        ),
        gateway=gateway,
        worker_id=worker_id,
    )


def _resolve_camera_ports(args: argparse.Namespace) -> tuple[str, str]:
    """--front-cam/--wrist-cam이 주어지면 그대로, 아니면 set_cameras.py로 저장해둔 값을 쓴다."""
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
    if args.orders:
        orders = mock_inputs.build_queue_from_specs(
            args.orders,
            start_job_step_id=9001,
            id_prefix="cli-deliver",
            pinky_delay_s=args.pinky_delay_s,
        )
    else:
        orders = mock_inputs.default_deliver_queue(args.zone)
    bench_ = bench.Bench()

    with robot_session.RobotSession(robot) as connected_robot:
        dataset_features = policy_runtime.build_dataset_features(connected_robot)

        for order_index, order in enumerate(orders):
            run_order(
                connected_robot,
                dataset_features,
                order,
                zone=args.zone,
                episode_steps=args.episode_steps,
                fps=args.fps,
                bench_=bench_,
                debug_gripper=args.debug_gripper,
                is_first_order=order_index == 0,
            )

    print("\n" + bench_.summary())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="OMX follower serial port, e.g. /dev/ttyACM0")
    parser.add_argument(
        "--zone", required=True, choices=KNOWN_ZONES,
        help="창고 구역. product_code가 이 구역 소속이 아니면 policy_catalog가 fail-closed로 "
             "거절한다(다른 구역 품목을 잘못 집으러 가지 않도록). chilled/ambient는 아직 "
             "학습된 정책이 없어 --order를 뭘 줘도 UnknownProductError로 끝난다.",
    )
    parser.add_argument(
        "--front-cam", default=None,
        help="front camera, e.g. /dev/video4 (권장: 전체 경로. 순수 숫자 인덱스는 "
             "Ubuntu에서 /dev/videoN과 1:1 대응이 보장되지 않음). 생략하면 "
             "set_cameras.py로 저장해둔 값을 씀.",
    )
    parser.add_argument(
        "--wrist-cam", default=None,
        help="wrist camera, e.g. /dev/video6 (권장: 전체 경로). 생략하면 "
             "set_cameras.py로 저장해둔 값을 씀.",
    )
    parser.add_argument(
        "--episode-steps", type=int, default=900,
        help="정책 최대 실행 스텝 수(안전 상한). pick+place 전체 사이클을 담을 만큼 "
             "충분히 커야 한다 — release가 확인되면 이 값에 도달하기 전에 자동으로 "
             "끝난다(조기 종료)이므로 넉넉하게 잡아도 손해가 없다. 기본값 900 = "
             "fps 15 기준 약 60초 (실측: 파지까지만 20초 걸리는 경우가 있어 450은 부족).",
    )
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument(
        "--cam-width", type=int, default=640,
        help="카메라 캡처 너비. 학습 데이터 녹화 해상도(640x480)와 맞춰야 한다.",
    )
    parser.add_argument(
        "--cam-height", type=int, default=480,
        help="카메라 캡처 높이. 학습 데이터 녹화 해상도(640x480)와 맞춰야 한다.",
    )
    parser.add_argument(
        "--cam-fps", type=int, default=30,
        help="카메라 캡처 fps(--fps와 다름, 후자는 정책 제어 루프 주기). "
             "카메라가 지원하는 고정값만 허용됨(lerobot이 요청값=실측값 일치를 요구).",
    )
    parser.add_argument(
        "--debug-gripper",
        action="store_true",
        help="매 스텝마다 그리퍼 Present_Current/Present_Position을 콘솔에 실시간 출력. "
             "grasp_check.py 임계값을 실측으로 튜닝할 때 사용.",
    )
    parser.add_argument(
        "--order",
        action="append",
        dest="orders",
        metavar="product_code:qty[,product_code:qty...]",
        help=(
            "주문 하나 추가, 여러 번 지정 가능. 예: --order dumpling:2 --order porkbelly:1. "
            "--zone과 일치하는 product_code만 허용됨 — 알려진 product_code: "
            f"frozen={policy_catalog.known_product_codes(zone='frozen')}, "
            f"chilled={policy_catalog.known_product_codes(zone='chilled')}, "
            f"ambient={policy_catalog.known_product_codes(zone='ambient')}. "
            "하나도 안 주면 mock_inputs.default_deliver_queue(zone)의 고정 큐를 씀."
        ),
    )
    parser.add_argument(
        "--pinky-delay-s",
        type=float,
        default=0.0,
        help="--order로 만든 모든 주문의 핑키 도착을 이만큼 지연 (0=즉시 도착, 안전 게이트 테스트용)",
    )
    return parser


if __name__ == "__main__":
    run(_parser().parse_args())
