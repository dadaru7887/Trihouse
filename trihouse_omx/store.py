#!/usr/bin/env python3
"""입고(store) — 로봇팔이 핑키 바구니에서 상품을 꺼내 원래 선반 위치에 놓는다.

--zone {frozen,chilled,ambient}로 창고 구역을 고른다(deliver.py와 동일).
deliver.py와 골격은 동일하다(로봇·카메라 1회 연결, 정책만 교체, 3·4번 인터페이스는
mock, 1·2번은 로컬 스텁). 차이는 두 가지뿐이다:

  1. 에피소드가 끝난 뒤 grasp_check.check_grasp 대신 grasp_check.check_release로
     "물체를 실제로 놓았는지"를 본다 (파지 확인의 반대 방향).
  2. policy_catalog.lookup_store를 쓰는데, 컨텍스트 문서 9번 항목대로 입고용
     체크포인트가 아직 하나도 학습되지 않아 이 카탈로그는 비어 있다. 그래서 기본
     실행은 UnknownStorePolicyError로 fail-closed한다 — 출고 체크포인트를 방향만
     바꿔 쓰면 안 되기 때문. 코드 경로(연결 유지·정책 스왑·추론 루프)만 확인하고
     싶으면 --policy-repo-id-override로 임의 체크포인트(예: 출고용)를 강제 지정할
     수 있는데, 이건 배관 테스트일 뿐 실제 놓는 동작으로서 의미는 없다.

실행 전: source ~/venv/il/bin/activate
실행 예 (입고 정책이 생기기 전, 배관 테스트용):
    python3 store.py --zone frozen --port /dev/ttyACM0 --front-cam /dev/video0 --wrist-cam /dev/video6 \\
        --policy-repo-id-override 2usang/act_trihouse-dumpling
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

# 정책 초반엔 그리퍼가 아직 목표를 향해 움직이는 중이라 파지/해제 판정이
# 무의미하다. 이 스텝 수만큼은 grasp_check/release_check를 건너뛴다.
GRASP_CHECK_START_STEP = 30

# release가 확인돼도 그 자리에서 바로 멈추지 않고 이만큼 더 정책을 실행한다.
# deliver.py와 동일한 이유 — release 확인 즉시 멈추면 팔이 뻗어 있는 채로 다음
# 아이템/주문으로 넘어가거나 disconnect(토크 해제)로 이어질 수 있는데, 토크가
# 꺼지면 지지되지 않은 자세에서 팔이 중력으로 그대로 무너진다 — 실제로 겪은 사고.
# deliver.py에서 100스텝으로 실측했을 때 복귀 막판에 살짝 못 미쳐 120으로 늘림.
POST_RELEASE_SETTLE_STEPS = 120


def _wait_for_pinky(pinky: mock_inputs.MockPinkyArrival, *, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if pinky.has_arrived():
            return True
        time.sleep(PINKY_POLL_INTERVAL_S)
    return pinky.has_arrived()


def _resolve_repo_id(item: mock_inputs.MockOrderItem, override: str | None, *, zone: str) -> tuple[str, str]:
    if override:
        return override, f"{item.product_code} (OVERRIDE, plumbing test only)"
    entry = policy_catalog.lookup_store(item.product_code, zone=zone)
    return entry.policy_repo_id, entry.label_ko


@dataclass(frozen=True)
class ItemVerdict:
    """물체 하나의 pick(바구니)+place(선반) 사이클 최종 판정.

    released만 보면 "그리퍼가 비어 있다"는 것만 확인되지, 애초에 바구니에서
    물건을 집기는 했는지는 알 수 없다(빈 그립으로 시작해 아무것도 안 집었어도
    끝까지 released=True로 보일 수 있음). grasped를 함께 확인해야 진짜
    pick+place가 일어난 것이다.
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
    policy_repo_id_override: str | None,
    debug_gripper: bool = False,
) -> ItemVerdict:
    """정책 하나를 실행해 물체 하나를 바구니에서 꺼내 선반에 놓는다.

    episode_steps는 pick(바구니)+place(선반) 전체 사이클을 담을 만큼 충분히
    커야 한다. deliver.py와 동일한 이유로, 파지 후 그리퍼가 다시 열려
    물건을 놓았다고 확인되는 순간(release confirmed) 바로 루프를 끝내고
    다음 아이템으로 넘어간다 — 그렇지 않으면 수량이 2개 이상인 주문에서
    시간이 남아 정책이 다음 물건을 향해 또 움직이기 시작할 수 있다.
    """
    repo_id, label = _resolve_repo_id(item, policy_repo_id_override, zone=zone)
    control_interval_s = 1.0 / fps

    grasp_verdict: grasp_check.GraspVerdict | None = None
    step_grasped: int | None = None
    release_verdict: grasp_check.ReleaseVerdict | None = None
    step_released: int | None = None
    settle_deadline: int | None = None
    grasp_debounce = grasp_check.Debouncer()
    release_debounce = grasp_check.Debouncer()

    with bench_.measure(order_id=order_id, product_code=item.product_code, is_first_order=is_first_order) as tick:
        loaded = policy_runtime.load_policy(repo_id)
        loaded.reset()
        tick("policy_loaded")

        for step in range(episode_steps):
            loop_start = time.perf_counter()
            action = policy_runtime.infer_step(robot, loaded, dataset_features, task=label)
            robot.send_action(action)
            if step == 0:
                tick("first_action")
            elapsed = time.perf_counter() - loop_start
            sleep_left = control_interval_s - elapsed
            if sleep_left > 0:
                time.sleep(sleep_left)

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
                    print(f"[{order_id}] item={item.product_code} grasped (from basket) at step {step} (debounced)")
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

    final_release = release_verdict if release_verdict is not None else grasp_check.check_release(robot)
    if release_verdict is not None and grasp_verdict is not None:
        reason = "PLACE_CONFIRMED"
    elif grasp_verdict is None:
        reason = "GRASP_NOT_CONFIRMED"
    else:
        reason = "RELEASE_NOT_CONFIRMED"

    return ItemVerdict(
        grasped=grasp_verdict is not None,
        released=release_verdict is not None,
        step_grasped=step_grasped,
        step_released=step_released,
        present_current=final_release.present_current,
        present_position=final_release.present_position,
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
    policy_repo_id_override: str | None = None,
    debug_gripper: bool = False,
    is_first_order: bool = False,
    gateway=None,
    worker_id: str = "trihouse-omx",
) -> None:
    """주문 하나(핑키 대기 → 품목별 pick(바구니)+place(선반) → 완료 보고)를 끝까지 처리한다.

    deliver.py의 run_order와 동일한 이유로 CLI(argparse.Namespace)에 묶이지 않게
    분리해뒀다 — job_loop.py가 입고 정책이 생긴 뒤 재사용할 수 있도록. gateway/worker_id도
    deliver.py의 run_order와 동일하게 outcome_report.report_outcome에 그대로 넘긴다.
    """
    print(f"\n=== order {order.order_id} (job_step_id={order.job_step_id}) ===")

    arrived = _wait_for_pinky(order.pinky, timeout_s=PINKY_ARRIVAL_TIMEOUT_S)
    if not arrived:
        outcome_report.report_outcome(
            outcome_report.StepOutcome(
                job_step_id=order.job_step_id,
                outcome="failed",
                assignment_revision=order.assignment_revision,
                method_code="OMX_STORE_MOCK",
                actor_device_id="OMX_01",
                reason_code="PINKY_NOT_ARRIVED",
                detail="fail-closed: no basket to pull from before pinky arrival",
            ),
            gateway=gateway,
            worker_id=worker_id,
        )
        print(f"[{order.order_id}] pinky did not arrive within timeout — skipping (fail-closed)")
        return

    # reserved_quantity만큼 물리적으로 따로 집어야 한다 — deliver.py의
    # run_order와 동일한 이유(정책 한 번 실행 = 그 품목 한 개 pick+place).
    units = [item for item in order.items for _ in range(item.reserved_quantity)]
    item_results = []
    try:
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
                policy_repo_id_override=policy_repo_id_override,
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
                # fail-closed: deliver.py와 동일한 이유 — release 미확인 상태로
                # 다음 물건을 집으러 가면 잔여 그리퍼 상태 때문에 다음 아이템의
                # grasp_check가 오탐한다.
                print(
                    f"[{order.order_id}] item={item.product_code} release 미확인 — "
                    "그리퍼 상태 불확실, 나머지 품목 중단 (fail-closed)"
                )
                break
    except policy_catalog.UnknownStorePolicyError as error:
        outcome_report.report_outcome(
            outcome_report.StepOutcome(
                job_step_id=order.job_step_id,
                outcome="failed",
                assignment_revision=order.assignment_revision,
                method_code="OMX_STORE_MOCK",
                actor_device_id="OMX_01",
                reason_code="NO_PLACE_POLICY",
                detail=str(error),
            ),
            gateway=gateway,
            worker_id=worker_id,
        )
        print(f"[{order.order_id}] {error}")
        return

    all_released = all(verdict.released for _, verdict in item_results)
    any_grasped = any(verdict.grasped for _, verdict in item_results)
    if all_released:
        reason_code = "PLACE_CONFIRMED"
    elif any_grasped:
        reason_code = "RELEASE_NOT_CONFIRMED"
    else:
        reason_code = "GRASP_NOT_CONFIRMED"
    outcome_report.report_outcome(
        outcome_report.StepOutcome(
            job_step_id=order.job_step_id,
            outcome="succeeded" if all_released else "failed",
            assignment_revision=order.assignment_revision,
            method_code="OMX_STORE_MOCK",
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
            start_job_step_id=9501,
            id_prefix="cli-store",
            pinky_delay_s=args.pinky_delay_s,
        )
    else:
        orders = mock_inputs.default_store_queue(args.zone)
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
                policy_repo_id_override=args.policy_repo_id_override,
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
             "거절한다. chilled/ambient는 입고 정책 자체가 아직 없어(policy_catalog.py) "
             "--policy-repo-id-override 없이는 항상 UnknownStorePolicyError로 끝난다.",
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
        help="정책 최대 실행 스텝 수(안전 상한). pick(바구니)+place(선반) 전체 사이클을 "
             "담을 만큼 충분히 커야 한다 — release가 확인되면 이 값에 도달하기 전에 "
             "자동으로 끝난다(조기 종료)이므로 넉넉하게 잡아도 손해가 없다. 기본값 900 = "
             "fps 15 기준 약 60초 (deliver.py 실측 근거로 맞춤).",
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
        "--policy-repo-id-override",
        default=None,
        help="배관 테스트용: 입고 정책이 없을 때 임의 체크포인트를 강제 지정 (의미상 올바른 동작 아님)",
    )
    parser.add_argument(
        "--order",
        action="append",
        dest="orders",
        metavar="product_code:qty[,product_code:qty...]",
        help="주문 하나 추가, 여러 번 지정 가능. 예: --order dumpling:1. --zone과 일치하는 "
             "product_code만 허용됨. 안 주면 mock_inputs.default_store_queue(zone) 사용.",
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
