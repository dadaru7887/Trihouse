#!/usr/bin/env python3
"""입고 바구니 하나(여러 구역 품목 혼재 가능)를 냉동→냉장→상온 순서로 처리한다.

흐름: 바구니에 물건이 실림(품목·수량 파악) -> 핑키가 냉동→냉장→상온 고정
순서로 이동 -> 각 구역에서 그 구역 몫만 적재 -> 빈 구역은 건너뜀 -> 대기
장소로 복귀. inbound_route.plan_zone_visits()가 "어느 구역을 들를지"만
순수하게 계산하고, 이 파일이 그 계획을 실제로 수행한다.

이 PC의 로봇팔은 물리적으로 구역 하나에 고정돼 있으므로(--hardware-zone),
계획된 방문 중 그 구역만 실제 하드웨어(store.run_order, 이미 검증된
pick+place/파지 디바운스/fail-closed 로직 그대로 재사용)로 수행하고, 나머지
구역은 "핑키가 이동해서 적재했을 것"이라는 시뮬레이션 로그만 남긴다 — 지금
단계는 냉동→냉장→상온 순서/빈 구역 스킵 로직 자체를 검증하는 게 목적이고,
실제 다구역 하드웨어 실행은 각 구역에 실제로 놓인 OMX PC가 각자
맡는다(job_loop.py). --hardware-zone/--port를 생략하면 하드웨어를 전혀
건드리지 않는 순수 라우팅 로직 확인(dry-run)만 한다.

실행 전: source ~/venv/il/bin/activate
실행 예 1 (하드웨어 없이 라우팅 로직만 확인 — 이 구역 순서/스킵이 맞는지):
    python3 store_basket.py --basket dumpling:2,coffee:1

실행 예 2 (이 PC가 frozen 담당일 때, frozen 몫만 실제 하드웨어로 실행):
    python3 store_basket.py --basket dumpling:2,coffee:1 --hardware-zone frozen \\
        --port /dev/ttyACM0 --front-cam /dev/video0 --wrist-cam /dev/video6
"""

from __future__ import annotations

import argparse
import itertools

import bench
import inbound_route
import mock_inputs
import policy_catalog

# robot_session/store(→policy_runtime)는 lerobot/torch가 있어야 import된다.
# --hardware-zone 없이 순수 라우팅 로직만 볼 때는(dry-run) lerobot venv조차
# 필요 없게 하려고, 이 두 모듈은 run() 안에서 하드웨어를 실제로 쓸 때만 늦게
# import한다.
KNOWN_ZONES = inbound_route.ZONE_VISIT_ORDER


def _print_plan(visits: tuple[inbound_route.ZoneVisit, ...], *, hardware_zone: str | None) -> None:
    print("[route] planned zone visits (fixed order 냉동→냉장→상온, 빈 구역 스킵):")
    for visit in visits:
        codes = ", ".join(f"{item.product_code}x{item.reserved_quantity}" for item in visit.items)
        marker = " <- this PC's hardware" if visit.zone == hardware_zone else " (simulated only)"
        print(f"  - {visit.zone}: {codes}{marker}")


def run(args: argparse.Namespace) -> None:
    items = mock_inputs.parse_items(args.basket)
    visits = inbound_route.plan_zone_visits(items)
    if not visits:
        print("[route] basket resolved to zero known items — nothing to visit")
        return
    _print_plan(visits, hardware_zone=args.hardware_zone)

    runs_hardware = any(visit.zone == args.hardware_zone for visit in visits)
    connected_robot = None
    dataset_features = None
    bench_ = bench.Bench()
    job_step_ids = itertools.count(args.start_job_step_id)

    policy_runtime_module = None
    if args.remote_infer_url:
        import remote_policy_runtime

        remote_policy_runtime.configure(base_url=args.remote_infer_url, timeout_s=args.remote_infer_timeout_s)
        policy_runtime_module = remote_policy_runtime
        print(f"[policy] 원격 추론 사용: {args.remote_infer_url}")

    robot_ctx = None
    store = None
    if runs_hardware:
        import policy_runtime
        import robot_session
        import store as store_module

        store = store_module
        if args.post_release_settle_steps is None:
            args.post_release_settle_steps = store.POST_RELEASE_SETTLE_STEPS
        front_cam, wrist_cam = store._resolve_camera_ports(args)
        robot = robot_session.build_robot(
            port=args.port,
            cameras=(
                robot_session.CameraSpec("front", front_cam, width=args.cam_width, height=args.cam_height, fps=args.cam_fps),
                robot_session.CameraSpec("wrist", wrist_cam, width=args.cam_width, height=args.cam_height, fps=args.cam_fps),
            ),
        )
        robot_ctx = robot_session.RobotSession(robot)
        connected_robot = robot_ctx.__enter__()

    try:
        for visit_index, visit in enumerate(visits):
            if visit.zone != args.hardware_zone:
                print(f"\n=== (simulated) Pinky -> {visit.zone} ===")
                for item in visit.items:
                    print(f"  (simulated) place {item.product_code} x{item.reserved_quantity} "
                          "— no hardware on this PC for this zone")
                continue

            if dataset_features is None:
                dataset_features = policy_runtime.build_dataset_features(connected_robot)

            order = mock_inputs.MockOrder(
                order_id=f"basket-{visit.zone}",
                job_step_id=next(job_step_ids),
                assignment_revision=1,
                items=visit.items,
                pinky=mock_inputs.MockPinkyArrival(already_arrived=True),
            )
            store.run_order(
                connected_robot,
                dataset_features,
                order,
                zone=visit.zone,
                episode_steps=args.episode_steps,
                fps=args.fps,
                bench_=bench_,
                policy_repo_id_override=args.policy_repo_id_override,
                debug_gripper=args.debug_gripper,
                is_first_order=visit_index == 0,
                policy_runtime_module=policy_runtime_module,
                post_release_settle_steps=args.post_release_settle_steps,
            )
    finally:
        if robot_ctx is not None:
            robot_ctx.__exit__(None, None, None)

    print("\n[route] all planned zones done — returning to standby")
    if dataset_features is not None:
        print("\n" + bench_.summary())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--basket", required=True,
        metavar="product_code:qty[,product_code:qty...]",
        help="바구니 하나에 실린 전체 품목(구역 혼재 가능). 예: dumpling:2,coffee:1",
    )
    parser.add_argument(
        "--hardware-zone", default=None, choices=KNOWN_ZONES,
        help="이 PC의 로봇팔이 실제로 놓여 있는 구역. 생략하면(기본값) 하드웨어를 "
             "전혀 건드리지 않고 방문 순서/스킵 로직만 출력한다(dry-run).",
    )
    parser.add_argument("--port", default=None, help="OMX follower serial port, e.g. /dev/ttyACM0 (--hardware-zone 줬을 때 필수)")
    parser.add_argument("--front-cam", default=None, help="생략하면 set_cameras.py 저장값을 씀")
    parser.add_argument("--wrist-cam", default=None, help="생략하면 set_cameras.py 저장값을 씀")
    parser.add_argument("--episode-steps", type=int, default=1000)
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument("--cam-width", type=int, default=640)
    parser.add_argument("--cam-height", type=int, default=480)
    parser.add_argument("--cam-fps", type=int, default=30)
    parser.add_argument("--debug-gripper", action="store_true")
    parser.add_argument("--policy-repo-id-override", default=None, help="배관 테스트용, store.py와 동일")
    parser.add_argument("--start-job-step-id", type=int, default=9601)
    parser.add_argument("--remote-infer-url", default=None)
    parser.add_argument("--remote-infer-timeout-s", type=float, default=5.0)
    parser.add_argument(
        "--post-release-settle-steps", type=int, default=None,
        help="생략하면(기본값) store.py의 기본값을 씀. store 모듈은 하드웨어를 실제로 쓸 "
             "때만 늦게 import되므로, 여기서는 store.POST_RELEASE_SETTLE_STEPS를 직접 "
             "참조하지 않는다(dry-run이 lerobot 없이도 동작해야 하기 때문).",
    )
    return parser


def _validate(args: argparse.Namespace) -> None:
    if args.hardware_zone and not args.port:
        raise SystemExit("--hardware-zone을 줬으면 --port도 필요하다(실제 하드웨어 연결 대상)")


if __name__ == "__main__":
    parsed = _parser().parse_args()
    _validate(parsed)
    try:
        run(parsed)
    except policy_catalog.UnknownProductError as error:
        raise SystemExit(f"[route] {error}") from error
