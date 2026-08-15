"""driving_v2_final -- FMS(1차 주행) + VLM+RL 복구까지 연결한 최종 주행 코드.

**이 파일은 초기 스캐폴드임 -- 로봇에 한 번도 안 돌려봄.** v1
(driving_v1_first_run/orchestrate_fms_v1_drive.py)의 FMS+narrow-zone 구조를 그대로 쓰고,
각 leg으로 Nav2 goal 보내기 직전에 카메라 한 프레임 보고 장애물 트리거가 뜨면 VLM+RL
복구 파이프라인을 한 번 거치는 훅만 추가한 버전.

**의도적으로 축소한 범위(오늘 밤 시간 한계로 인한 것, 나중에 확장 필요)**:
- 원래 설계(orchestrate_live_teleop.py)는 Nav2 goal 실행 "중에" 논블로킹으로 계속
  세그멘테이션을 보면서 트리거를 잡는데, 이 스캐폴드는 **각 leg 시작 전에 딱 한 프레임만
  보고 판단**함(연속 모니터링 아님). 실제로 쓰려면 chained_waypoint_drive.py의 논블로킹
  패턴을 가져와야 함.

**이 스캐폴드가 새로 만든 문제가 아니라 원래부터 있던 한계(EVOLUTION.md 참고)**:
- `recovery_filters.py`의 stage5(6C-Lite)가 기본적으로 fail-closed -- `geometric_6c_lite.py`를
  FilterContext에 실제로 연결 안 하면 후보가 절대 통과 못 함. 이 스캐폴드도 아직 안 연결함
  -- 즉 지금 이대로 돌리면 "트리거는 뜨고 VLM/RL 후보도 생성되는데, recovery 실행은 항상
  거부됨"(로그만 남고 로봇은 안 움직임 -- 안전한 상태로 멈추는 것뿐, 위험하게 동작 안 함).
- `recovery_system_node.py`(학습된 checkpoint 로드)가 없어서 매번 미학습 정책으로 새로
  초기화함.
- Gateway API 연동은 v1과 동일한 상태(GatewayAPIStub, FROZEN_PICKUP만 매핑 가능).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import requests
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from tf2_ros import Buffer, TransformListener
from geometry_msgs.msg import Twist
from nav2_msgs.action import NavigateToPose

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "driving_fms"))
sys.path.insert(0, str(HERE.parent / "driving_v1_first_run"))
sys.path.insert(0, str(HERE.parent / "driving_vlm_rl" / "02_pipeline_core"))

from mission_goal_state_machine import MissionGoalStateMachine  # noqa: E402
from mission_goal_state_machine_v2 import (  # noqa: E402
    current_target_v2, is_departing_from_start_zone_1,
)
from narrow3_rule_based_docking import (  # noqa: E402
    depart_from_start_zone_1, get_pose, run_zone_sequence,
)
from orchestrate_fms_v1_drive import (  # noqa: E402
    GatewayAPIStub, default_battery_low_fn, send_nav2_goal,
)

# VLM+RL 파이프라인 조각들 -- 02_pipeline_core에서 그대로 가져옴
from vlm_contract_to_rl_state import vlm_json_to_state  # noqa: E402
from rl_candidate_group import RLCandidate, sample_candidate_group  # noqa: E402
from recovery_filters import (  # noqa: E402
    Candidate, FilterContext, RecoveryEnvelope, RobotState, SensorSnapshot,
    run_generation_filters, run_rollout_filters,
)
from tgrpo_sac_hierarchical_v2 import HighLevelPolicy, LowLevelPolicy  # noqa: E402

MAX_LEGS = 30
ROBOT_FRAME_URL = "http://192.168.129.23:8899/frame"  # TODO: 로봇 IP 바뀌면 갱신
CANDIDATE_K, CANDIDATE_M = 3, 2  # orchestrate_live_teleop.py 기본값 그대로 재사용


def rl_candidate_to_filter_candidate(rl_cand: RLCandidate, map_revision: str,
                                      footprint_class: str, epoch: int,
                                      timestamp: float) -> Candidate:
    """rl_candidate_group.RLCandidate(skill/offset 중심) -> recovery_filters.Candidate
    (map frame 절대좌표 중심)로 변환. **이 둘이 서로 다른 클래스라는 걸 처음엔 놓치고
    RLCandidate를 그냥 필터 함수에 바로 넘기려다가 필드가 안 맞는 걸 뒤늦게 발견함** --
    orchestrate_live_teleop.py 원본에도 이 변환이 있을 텐데 이 스캐폴드에선 최소 필드만
    채워서 새로 씀."""
    return Candidate(
        candidate_id=f"skill{rl_cand.skill}_{timestamp:.3f}",
        x=rl_cand.map_x, y=rl_cand.map_y, yaw=rl_cand.map_yaw,
        map_frame="map", map_revision=map_revision, footprint_class=footprint_class,
        source_episode_id=None, source_policy_bundle=None,
        policy_epoch=epoch, is_stable_bundle=False, timestamp=timestamp,
    )


def check_segmentation_trigger(seg_model) -> tuple[bool, list[dict]]:
    """카메라 한 프레임 받아서 obstacle 감지 여부만 봄 -- **오늘 밤 만든 축소판**,
    실제 ObjectWatcher(신규출현/경로상물체/접근중, orchestrate_live_teleop.py)의 3조건
    휴리스틱은 안 씀. 감지=바로 트리거(--simple-trigger 모드와 동일 원칙, 배선 검증용)."""
    try:
        resp = requests.get(ROBOT_FRAME_URL, timeout=1.0)
    except requests.RequestException as e:
        print(f"!! 프레임 요청 실패: {e} -- 트리거 스킵하고 진행")
        return False, []
    # segment_image()가 파일 경로를 받는 구조라 임시 저장 -- vlm_contract_to_rl_state.py
    # 원본 인터페이스를 안 건드리려고 이렇게 함(리팩터링은 다음 작업).
    tmp_path = "/tmp/_v2_trigger_frame.jpg"
    with open(tmp_path, "wb") as f:
        f.write(resp.content)
    from vlm_contract_to_rl_state import segment_image
    detections, _ = segment_image(seg_model, tmp_path)
    return len(detections) > 0, detections


def run_vlm_rl_recovery(node: Node, buf: Buffer, pub, seg_model,
                         high_policy: HighLevelPolicy, low_policy: LowLevelPolicy) -> None:
    """트리거 뜨면 호출 -- VLM 판단 -> RL 후보 생성 -> 안전필터. 필터를 실제로 통과하는
    후보가 지금 구조상 없어서(stage5 fail-closed, 위 docstring 참고) **여기서 실행까지는
    안 감** -- 로그만 남기고 리턴, Nav2 정상 진행은 호출부가 계속함."""
    pose = get_pose(buf)
    if pose is None:
        print("  [recovery] TF 못 얻음, 스킵")
        return
    x, y, yaw = pose

    # TODO: 실제 VLM 호출(call_vlm_contract)은 모델/프로세서 로딩이 무거워서 이 스캐폴드
    # 에서는 생략 -- vlm_json을 최소 형태로 직접 구성해서 나머지 배선만 확인.
    vlm_json_stub = {"observations": [], "uncertainty": 0.5}
    state = vlm_json_to_state(vlm_json_stub, robot_pos=(x, y), robot_yaw=yaw,
                               goal_pos=(x, y))  # TODO: 실제 goal_pos(다음 FMS target) 연결

    rl_candidates = sample_candidate_group(
        high_policy, low_policy, state, robot_pose=(x, y, yaw),
        k=CANDIDATE_K, m=CANDIDATE_M, device="cpu",  # TODO: GPU 확인되면 "cuda"로
    )
    now = time.time()
    candidates = [
        rl_candidate_to_filter_candidate(
            rc, map_revision="unknown", footprint_class="default", epoch=0, timestamp=now)
        for rc in rl_candidates
    ]
    print(f"  [recovery] 후보 {len(candidates)}개 생성됨(RLCandidate -> Candidate 변환됨)")

    # RobotState는 위치가 아니라 "정지했는지"(R0-01/02) 체크용 -- 처음에 x/y/yaw로
    # 잘못 넣었다가 recovery_filters.py 원본 필드 다시 확인하고 고침(linear/angular_speed).
    # 지금은 실제 /cmd_vel 피드백이 없어서 "이미 멈춰있다" stub으로 둠.
    robot_state = RobotState(linear_speed=0.0, angular_speed=0.0)
    # SensorSnapshot도 timestamp가 필수 필드라 반드시 채워야 함 -- bumper/estop/
    # safety_supervisor는 원본 기본값(False, 하드웨어 없어서 fail-closed)을 그대로 둠.
    snapshot = SensorSnapshot(timestamp=time.time())
    # FilterContext -- envelope(RecoveryEnvelope)이 필수라 임시로 로봇 현재 위치 중심,
    # 반경 1.0m짜리로 stub. 실제로는 미션 설계 문서의 Recovery Envelope 규칙대로 계산해야 함.
    envelope = RecoveryEnvelope(center_x=x, center_y=y, radius_m=1.0,
                                 max_path_length_m=2.0, epoch=0)
    ctx = FilterContext(
        current_epoch=0, current_map_revision="unknown",
        current_footprint_class="default", envelope=envelope,
        robot_pose_x=x, robot_pose_y=y, robot_pose_yaw=yaw,
    )  # TODO: query_* 콜백들 nav2_costmap_query.build_filter_context_queries()로 실제 연결

    gen_reports = run_generation_filters(candidates, robot_state, snapshot, ctx)
    survivors_gen = [r for r in gen_reports if r.passed]
    print(f"  [recovery] 0~3단계 통과: {len(survivors_gen)}/{len(candidates)}")

    rollout_reports = run_rollout_filters(candidates, ctx)
    survivors_final = [r for r in rollout_reports if r.passed]
    print(f"  [recovery] 4~5단계(6C-Lite 미연결, fail-closed 예상) 통과: "
          f"{len(survivors_final)}/{len(candidates)}")
    if not survivors_final:
        print("  [recovery] 통과 후보 없음 -- 실행 안 하고 Nav2로 계속 진행(안전한 기본 동작)")
        return

    # TODO: survivors_final 중 우승 선정 + nav_recovery_executor.execute_and_observe_real()로
    # 실제 실행. stage5가 항상 막혀있는 지금 구조상 여기 도달 안 함 -- 6C-Lite 연결 후 이어서.
    print("  [recovery] TODO: 우승 후보 실행 로직 -- 아직 구현 안 함")


def run_mission_v2(node: Node, buf: Buffer, pub, nav2_client: ActionClient,
                    gateway: GatewayAPIStub, seg_model, high_policy: HighLevelPolicy,
                    low_policy: LowLevelPolicy, battery_low_fn=default_battery_low_fn) -> None:
    zone_slot, loading_targets = gateway.get_mission_assignment()
    fsm = MissionGoalStateMachine(zone_slot=zone_slot)

    if is_departing_from_start_zone_1(fsm):
        print("[출발] narrow_4 회피용 직진 먼저 시도")
        depart_from_start_zone_1(node, buf, pub)

    fsm.set_loading_targets(loading_targets)

    for leg_i in range(MAX_LEGS):
        pose = get_pose(buf)
        if pose is None:
            print("!! TF 못 얻음 -- 중단"); return
        x, y, yaw = pose

        battery_low = battery_low_fn()
        occupied_end_slots = gateway.get_occupied_end_slots()
        target, narrow_zone = current_target_v2(
            fsm, x, y, battery_low=battery_low, occupied_end_slots=occupied_end_slots)
        print(f"\n[leg {leg_i+1}] stage={fsm.stage}, target={target.id}, narrow_zone={narrow_zone}")

        if not target.ready:
            print("!! 목표 좌표 없음 -- 중단"); return

        # v1과의 차이 -- narrow zone 아니면 Nav2 보내기 전에 트리거 체크 한 번
        if not narrow_zone:
            triggered, detections = check_segmentation_trigger(seg_model)
            if triggered:
                print(f"  -> 트리거 감지({len(detections)}개 물체), VLM+RL 복구 파이프라인 호출")
                run_vlm_rl_recovery(node, buf, pub, seg_model, high_policy, low_policy)

        if narrow_zone:
            ok = run_zone_sequence(node, buf, pub, narrow_zone)
        else:
            ok = send_nav2_goal(node, nav2_client, target.x, target.y, target.yaw, yaw)

        if not ok:
            print(f"!! leg {leg_i+1} 실패({target.id}) -- 중단"); return

        if fsm.stage.name == "LOADING":
            fsm._loading_idx += 1  # TODO: confirm_arrival_by_aruco()로 정식 교체
        elif fsm.stage.name == "DELIVERING":
            fsm.mark_delivery_done()
        elif fsm.stage.name == "END":
            print("복귀 완료, 미션 종료"); return


def main() -> None:
    rclpy.init()
    node = Node("orchestrate_fms_vlm_rl_drive_v2")
    buf = Buffer()
    TransformListener(buf, node)
    pub = node.create_publisher(Twist, "/cmd_vel", 10)
    nav2_client = ActionClient(node, NavigateToPose, "navigate_to_pose")

    for _ in range(20):
        rclpy.spin_once(node, timeout_sec=0.1)
    nav2_client.wait_for_server(timeout_sec=10.0)

    print("YOLO 세그멘테이션 모델 로딩...")
    from ultralytics import YOLO
    seg_model = YOLO("weights/aug_best.pt")  # TODO: 실제 경로 확인
    from train import mixed_augmentation  # noqa: F401  # 체크포인트 로드용 placeholder

    high_policy = HighLevelPolicy()
    low_policy = LowLevelPolicy()
    # TODO: recovery_system_node.py 없어서 checkpoint 로드 코드 자체가 없음 -- 매번 미학습.
    gateway = GatewayAPIStub()

    try:
        run_mission_v2(node, buf, pub, nav2_client, gateway, seg_model,
                        high_policy, low_policy)
    except KeyboardInterrupt:
        pub.publish(Twist())
        print("\nCtrl+C -- 정지")
    finally:
        pub.publish(Twist())
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
