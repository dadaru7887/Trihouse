"""1차 주행(순수 Nav2+FMS, VLM/RL 안 거침) 메인 드라이버 -- 데모/스캐폴드.

오늘 밤 만든 세 조각을 하나로 잇는 코드:
1. mission_goal_state_machine_v2.py -- 다음 목표 + narrow_zone 태그 판단
2. narrow3_rule_based_docking.py -- 좁은 구간(narrow_1/2/3/5, start_zone_1 출발)은 Nav2 대신 규칙기반
3. 그 외 구간은 평소대로 Nav2 NavigateToPose

**이 파일은 데모/스캐폴드임 -- 로봇에 실제로 돌려본 적 없음.** narrow3_rule_based_docking.py의
TODO(zone 좌표/거리값)들이 다 채워지고, 실제 로봇 연결된 상태에서 처음부터 검증 필요.
구조(각 조각을 어떤 순서로 부르는지)만 확정하려는 목적으로 짜둔 것.

전제: 이 파일을 driving_fms/, driving_v1_first_run/ 둘 다 import 경로에 있는 상태로 실행
(같은 레포 안이라 상대 경로로 처리, 아래 sys.path 참고).
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from tf2_ros import Buffer, TransformListener
from tf_transformations import euler_from_quaternion, quaternion_from_euler
from geometry_msgs.msg import Twist
from nav2_msgs.action import NavigateToPose

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "driving_fms"))
sys.path.insert(0, str(HERE))

from mission_goal_state_machine import MissionGoalStateMachine  # noqa: E402
from mission_goal_state_machine_v2 import (  # noqa: E402
    current_target_v2, is_departing_from_start_zone_1,
)
from narrow3_rule_based_docking import (  # noqa: E402
    depart_from_start_zone_1, get_pose, run_zone_sequence, ZONES,
)

MAX_LEGS = 30           # 무한루프 방지용 안전장치(디버깅 중 무한 반복 막기)
NAV2_GOAL_TIMEOUT = 30.0


# 2026-08-15 밤 -- 전체 경로를 끝까지 추적한 최종 결론 (docs/guideline/waypoint.md +
# db/schema_mysql.sql + fms_gateway/app/{main,repositories,models}.py, 전부
# feat/pinky-edge-agent / dev_db 브랜치 원본 직접 확인).
#
# 1) DB 스키마엔 `locations.temperature_zone IN ('ambient','chilled','frozen')` 실제로 있음
#    (db/schema_mysql.sql 확인) -- 상온/냉장/냉동 3종 다 스키마 레벨에선 지원됨.
# 2) `job_steps.target_location_id`가 그 location을 가리킴 (FK, 스키마 확인).
# 3) 하지만 **`GET /api/v1/jobs/{job_id}`(JobDetail)의 실제 구현(repositories.py
#    get_job())이 locations 테이블을 join하지 않음** -- steps에 target_location_id
#    (숫자 FK)만 오고 temperature_zone/rmf_waypoint_name은 안 옴.
# 4) **location 상세를 조회하는 API 엔드포인트 자체가 main.py에 없음** (전체 검색 확인,
#    "안 찾아진" 게 아니라 "없는 것" 확인됨).
#
# 즉 지금 서버 코드 상태로는 로봇이 job_step을 claim해도 그게 냉동/냉장/상온 중
# 어딘지 알아낼 API가 없음 -- 이건 우리 쪽 문제가 아니라 DB/Gateway 팀에 실제로 필요한
# 엔드포인트가 빠진 것([[vlm_rl_db_schema_delivered]] 9개 후속질문과 같은 성격의 진짜 갭,
# 다음에 DB팀한테 "GET /api/v1/locations/{id} 같은 거 추가해달라" 요청할 근거로 쓸 것).
#
# 그래서 지금 할 수 있는 최선은: FROZEN_PICKUP 하나만 waypoint 문서에 이름까지 있어서
# 확실하고, 나머지는 저 API가 생기기 전까진 매핑 자체가 불가능함을 명시.
RMF_WAYPOINT_PREFIX_TO_LOADING_NUM = {
    "FROZEN_PICKUP": 3,   # 냉동 -> sub_sub_midgoal_3 -> narrow_3. 공식 문서로 확인된 유일한 매핑.
    # TODO(DB/Gateway 팀 확인 필요): location 상세 조회 API가 생기면, temperature_zone
    # 'chilled'->2, 'ambient'->1로 매핑하는 게 이름 문자열 파싱보다 훨씬 안정적임(스키마
    # 컬럼이라 enum 값이 고정돼있어서) -- API 생기면 이 dict 대신 temperature_zone 기준으로 교체.
}


def rmf_waypoint_name_to_loading_num(rmf_waypoint_name: str) -> int | None:
    """"FROZEN_PICKUP_01" 같은 이름에서 우리 sub_sub_midgoal 번호로 변환. 지금은
    FROZEN_PICKUP만 확실함(공식 문서 실측 확인) -- 상온/냉장은 DB에 temperature_zone
    컬럼은 있지만 그걸 조회할 API가 서버에 아직 없어서 None 반환(호출부가 처리 못 하면
    Nav2 대신 사람이 판단해야 함을 뜻함)."""
    prefix = rmf_waypoint_name.rsplit("_", 1)[0]  # "FROZEN_PICKUP_01" -> "FROZEN_PICKUP"
    return RMF_WAYPOINT_PREFIX_TO_LOADING_NUM.get(prefix)


class GatewayAPIStub:
    """DB/Gateway API 연동 전까지 쓰는 기본 구현.

    **2026-08-15 밤 발견, 중요한 정정**: 처음엔 "이 클래스랑 똑같은 시그니처로 실제 클래스만
    만들면 된다"고 생각했는데, `feat/pinky-edge-agent` 브랜치에 이미 실제 동작하는 Gateway
    클라이언트(`trihouse_rmf_bridge/trihouse_rmf_bridge/fms_client.py`,
    `FmsCommandClaimClient`)가 있고, 그건 **RMF(Open-RMF) 태스크 claim 모델**이라 여기
    아래 메서드들(zone_slot/loading_targets를 직접 물어보는 pull 방식)이랑 구조가 다름 --
    실제로는 `claim(rmf_task_id, robot_id, execution_id, map_revision)`을 호출해서
    `job_id/job_step_id/command_id` 등을 받아오고, **그 job_step_id를 "어느 적재구역으로
    갈지"로 변환하는 매핑 로직이 별도로 필요함**(이 매핑은 아직 어디에도 없어 보임).
    즉 여기 아래 GatewayAPIStub은 "실제 연동 시 이 모양 그대로 교체" 수준이 아니라 순수
    자리표시자(placeholder)임 -- 진짜 연동은 fms_client.py부터 읽고 job_step_id 매핑
    설계부터 다시 해야 함. run_mission()은 이 stub 인터페이스만 보고 동작하므로(의존성
    주입), 나중에 진짜 구현으로 바꿀 때 run_mission() 자체는 안 건드려도 되는 점은 여전히
    유효함 -- 다만 그 "진짜 구현"이 예상보다 훨씬 복잡함.

    주의: 배터리 위급 신호는 여기 없음 -- [[vlm_rl_waypoint_battery_design]] 설계 원칙대로
    DB/Gateway가 아니라 로봇 로컬 ROS2 토픽(battery_watcher.py 계열)에서 직접 읽어야 함,
    학습 중인 정책은 물론 DB 지연에도 안전 필수 로직을 맡기면 안 된다는 이유로 이미 결정된
    사항 -- 그래서 battery_low_fn은 별도 파라미터로 분리해뒀음(아래 run_mission 참고)."""

    def get_mission_assignment(self) -> tuple[int, list[int]]:
        """(zone_slot, loading_targets) -- 실제로는 Gateway API가 주문 정보 받아서 결정.
        지금은 하드코딩(냉동 하나만, 슬롯 1)."""
        return 1, [3]  # TODO: Gateway API 연동 시 실제 주문 조회로 교체

    def get_occupied_end_slots(self) -> set[int] | None:
        """None = 원본 FSM의 fail-safe(고정 슬롯 1번 우선) 그대로 사용.
        실제로는 다른 로봇들이 지금 어느 end_zone 슬롯 차지하고 있는지 Gateway가 알려줘야 함."""
        return None  # TODO: Gateway API 연동 시 실제 점유 현황으로 교체

    def get_occupied_bottlenecks(self) -> set[str] | None:
        """마찬가지로 다중로봇 병목 점유 현황 -- 원본 FSM의 bottleneck_should_wait()/
        bottleneck_should_yield()가 받는 신호. 지금은 이 데모 자체가 로봇 1대 가정이라
        안 씀(아래 run_mission에서 호출 안 함), 다중 로봇 붙일 때 배선 필요."""
        return None  # TODO: Gateway API 연동 시 실제 병목 점유 현황으로 교체


def default_battery_low_fn() -> bool:
    """로컬 배터리 신호 자리 -- 실제로는 battery_watcher.py가 구독하는
    /battery_publihser(오타 그대로, 실측 확인된 실제 토픽명) 값 기준으로 판단해야 함.
    DB/Gateway 관련 아님, GatewayAPIStub과 분리해둔 이유가 이거임."""
    return False  # TODO: battery_watcher.py 연동 시 실제 로컬 토픽 값으로 교체


def send_nav2_goal(node: Node, client: ActionClient, x: float, y: float,
                    yaw: float | None, current_yaw_fallback: float) -> bool:
    """평소 구간(narrow zone 아닌 곳)용 -- 오늘 밤 검증된 NavigateToPose 패턴 재사용
    (send_wp1.py에서 쓴 것과 동일한 구조)."""
    target_yaw = yaw if yaw is not None else current_yaw_fallback
    q = quaternion_from_euler(0, 0, target_yaw)
    goal = NavigateToPose.Goal()
    goal.pose.header.frame_id = "map"
    goal.pose.header.stamp = node.get_clock().now().to_msg()
    goal.pose.pose.position.x = x
    goal.pose.pose.position.y = y
    goal.pose.pose.orientation.x = q[0]
    goal.pose.pose.orientation.y = q[1]
    goal.pose.pose.orientation.z = q[2]
    goal.pose.pose.orientation.w = q[3]

    future = client.send_goal_async(goal)
    rclpy.spin_until_future_complete(node, future, timeout_sec=10.0)
    gh = future.result()
    if gh is None or not gh.accepted:
        print("!! Nav2 goal 거부됨")
        return False
    try:
        rf = gh.get_result_async()
        rclpy.spin_until_future_complete(node, rf, timeout_sec=NAV2_GOAL_TIMEOUT)
    except KeyboardInterrupt:
        # 2026-08-14 밤 안전패치 원칙 재사용 -- 타임아웃/인터럽트 시 명시적 취소
        cancel_future = gh.cancel_goal_async()
        rclpy.spin_until_future_complete(node, cancel_future, timeout_sec=5.0)
        raise
    res = rf.result()
    return res is not None


def run_mission(node: Node, buf: Buffer, pub: object, nav2_client: ActionClient,
                 gateway: GatewayAPIStub, battery_low_fn=default_battery_low_fn) -> None:
    """gateway/battery_low_fn을 인자로 받아서(하드코딩 안 함) -- 나중에 실제 Gateway API
    클라이언트/battery_watcher 연동할 때 이 함수 자체는 안 건드리고 호출부(main())에서
    넘기는 객체/함수만 실제 구현으로 바꾸면 됨."""
    zone_slot, loading_targets = gateway.get_mission_assignment()
    fsm = MissionGoalStateMachine(zone_slot=zone_slot)

    # narrow_4 회피 -- 미션 시작 시 한 번만, start_zone_1 출발인 경우만 적용
    if is_departing_from_start_zone_1(fsm):
        print("[출발] start_zone_1 근처면 narrow_4 회피용 직진 먼저 시도")
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
        print(f"\n[leg {leg_i+1}] stage={fsm.stage}, target={target.id}, "
              f"narrow_zone={narrow_zone}")

        if not target.ready:
            print("!! 목표 좌표 없음(FeaturePoint 미준비) -- 중단"); return

        if narrow_zone:
            print(f"  -> narrow zone 감지, Nav2 대신 규칙기반 시퀀스({narrow_zone}) 실행")
            ok = run_zone_sequence(node, buf, pub, narrow_zone)
        else:
            print(f"  -> 평소대로 Nav2 NavigateToPose ({target.x:.3f},{target.y:.3f})")
            ok = send_nav2_goal(node, nav2_client, target.x, target.y, target.yaw, yaw)

        if not ok:
            print(f"!! leg {leg_i+1} 실패({target.id}) -- 중단, 사람 확인 필요")
            return

        # 도착 후 stage 전이 -- 실제로는 confirm_arrival_by_aruco/mark_delivery_done 등
        # 원본 API를 상황(적재/배송/복귀)에 맞게 호출해야 하는데, 이 데모는 구조만 보여주는
        # 목적이라 단순화함. 실제 배포 전 원본 mission_goal_state_machine.py의 각 전이
        # 메서드 시그니처 다시 확인하고 정확히 연결할 것(TODO).
        if fsm.stage.name == "LOADING":
            fsm._loading_idx += 1  # TODO: confirm_arrival_by_aruco()로 정식 교체
        elif fsm.stage.name == "DELIVERING":
            fsm.mark_delivery_done()
        elif fsm.stage.name == "END":
            print("복귀 완료, 미션 종료"); return


def main() -> None:
    rclpy.init()
    node = Node("orchestrate_fms_v1_drive")
    buf = Buffer()
    TransformListener(buf, node)
    pub = node.create_publisher(Twist, "/cmd_vel", 10)
    nav2_client = ActionClient(node, NavigateToPose, "navigate_to_pose")

    for _ in range(20):
        rclpy.spin_once(node, timeout_sec=0.1)
    nav2_client.wait_for_server(timeout_sec=10.0)

    try:
        # Gateway API 연동 시: GatewayAPIStub() 자리에 실제 API 클라이언트 클래스만 넣으면 됨
        # (get_mission_assignment/get_occupied_end_slots/get_occupied_bottlenecks 동일 시그니처로 구현).
        # battery_low_fn도 마찬가지로 battery_watcher.py 연동 시 그 함수로 교체.
        gateway = GatewayAPIStub()
        run_mission(node, buf, pub, nav2_client, gateway=gateway,
                    battery_low_fn=default_battery_low_fn)
    except KeyboardInterrupt:
        pub.publish(Twist())
        print("\nCtrl+C -- 정지")
    finally:
        pub.publish(Twist())
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
