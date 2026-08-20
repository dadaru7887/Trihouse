"""narrow_1/2/3(상온/냉장/냉동) 전용 -- Nav2/RPP 대신 직접 cmd_vel로 좁은 코너 진입 처리.
오늘 밤 여러 파라미터(inflation/lookahead/rotate_to_heading/allow_reversing)를 다 시도해도
RPP가 냉동구역(narrow_3) 코너에서 계속 collision ahead로 막혀서, 이런 좁은 구간만 규칙
기반으로 우회하기로 결정한 것. `replay_trajectory.py`(사람이 teleop으로 시연한 궤적 재생)와
같은 원칙(costmap collision-check 없이 직접 cmd_vel) 재사용, 대신 "시연"이 아니라 zone마다
필요한 스텝 수가 다른 **명시적 시퀀스**로 구조화한 버전.

zone마다 스텝 구성이 다름(오늘 사진 기준):
- narrow_1(상온), narrow_2(냉장): 진입이 비교적 직선이라 [회전 -> 후진] 2단계면 충분해 보임
- narrow_3(냉동): 오늘 실측 결과 [직진 -> 회전 -> 후진] 3단계로 확정

**주의**: 이 스크립트도 LiDAR 충돌 감지가 없음(replay_trajectory.py와 동일한 트레이드오프).
반드시 사람이 로봇 옆에서 지켜보다가 이상하면 Ctrl+C.

실행: python3 narrow3_rule_based_docking.py <zone_name>   (예: narrow_1, narrow_2, narrow_3)

로봇에 배포 전 반드시 ZONES 딕셔너리의 TODO 채우기.
"""
from __future__ import annotations

import math
import sys
import time

import rclpy
from rclpy.node import Node
from tf2_ros import Buffer, TransformListener
from tf_transformations import euler_from_quaternion
from geometry_msgs.msg import Twist

from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose
from action_msgs.msg import GoalStatus

from rcl_interfaces.srv import SetParameters
from rcl_interfaces.msg import Parameter, ParameterValue, ParameterType



MAX_LIN = 0.06
MAX_ANG = 0.5
YAW_TOL = 0.05
POS_TOL = 0.02

NARROW_3_PRE_GOAL = {
    "x": 0.8198039894575488,
    "y": -1.1892528962848725,
    "yaw": -0.03242978898931081,
}

NARROW_3_FINAL_GOAL = {
    "x": 0.919825019,
    "y": -1.187955905,
    "yaw": -0.03242978898931081,
}

# ============================================================
# zone별 설정 -- 전부 TODO, 오늘 노트/사진 실측값으로 채우기.
#
# geometry: 진입 영역(중심좌표, 통로 yaw, 길이/폭) -- in_oriented_zone()이 체크
# sequence: [("rotate", target_yaw), ("straight", distance), ...] 순서대로 실행.
#           distance는 +전진/-후진. "straight"에서 distance<0이면 그 스텝은 후진.
# ============================================================
ZONES: dict[str, dict] = {
    "narrow_1": {  # 상온
        "geometry": {
            # 2026-08-15 실측 시작점 (stddev x=10.9cm/y=6.0cm/yaw=10.6deg)
            "cx": 1.010244055594586, "cy": 0.9167344977253539, "yaw": -0.08675495954950327,
            "length": 0.05, "width": 0.20,        # 2026-08-15 실측: 세로 5cm, 가로 20cm
        },
        # 2026-08-15 실측: 존 진입 후 바로 -- 현재 yaw로 회전 -> 30cm 후진, 2단계.
        "sequence": [  # 입고
            ("rotate", -2.805721254488808),  # 1) 주차 방향 -- 2026-08-15 마지막에 재저장한 값
            ("straight", -0.30),             # 2) 30cm 후진
        ],
        # 2026-08-15 실측: 출고 -- 30cm 직진(후진 되돌리기) -> 회전(-179.4deg) -> zone 벗어날 때까지 전진
        "sequence_exit": [
            ("straight", 0.30),
            ("rotate", -3.130293455959265),  # stddev yaw=11.3deg
            ("exit_zone", None),
        ],
    },
    "narrow_2": {  # 냉장
        "geometry": {
            # 2026-08-15 실측 시작점 (stddev x=11.5cm/y=6.9cm/yaw=13.0deg)
            "cx": 1.1013315221281241, "cy": -0.10045055614140724, "yaw": 3.1029342608092607,
            "length": 0.05, "width": 0.20,        # narrow_1과 동일
        },
        # narrow_1과 시퀀스 동일(회전/거리값은 narrow_1 값 그대로 재사용, 미검증 -- 다음에 확인 필요)
        "sequence": [
            ("rotate", 2.4189105956431427),
            ("straight", -0.30),
        ],
        "sequence_exit": [
            ("straight", 0.30),
            ("rotate", -3.130293455959265),
            ("exit_zone", None),
        ],
    },
    "narrow_3": {  # 냉동 -- 오늘 씨름했던 코너, 실측 완료(직진->회전->후진 3단계)
        "geometry": {
            # 2026-08-15 실측 (x=0.920, y=-1.189, yaw=-0.032rad, stddev x=15.8cm/y=4.3cm/yaw=17.5deg)
            "cx": 0.9198039894575488, "cy": -1.1892528962848725, "yaw": -0.03242978898931081,
            "length": 0.10, "width": 0.20,        # 2026-08-15 실측: 세로(진행축) 10cm, 가로(양쪽벽사이) 20cm
        },
        # 2026-08-15 실측 (재측정): 존 진입 -> 10cm 직진 -> 처음 각도로 회전 -> 31.5cm 후진.
        "sequence": [  # 입고(냉동구역 안으로 들어가기)
            ("straight", 0.375),                # 1) 존 진입 후 0.40cm 직진
            ("rotate", -0.9057963267948966),   # 2) 처음 저장한 각도로 제자리 회전
            ("straight", -0.368),              # 3) 31.5cm 후진
        ],
        # 2026-08-15 실측: 출고(냉동구역에서 나오기) -- 입고의 역순.
        "sequence_exit": [
            ("straight", 0.315),               # 1) 후진했던 만큼(31.5cm) 다시 전진
            ("rotate", -2.999132807834344),    # 2) 출고 방향(-171.8deg)으로 제자리 회전
            ("exit_zone", None),               # 3) in_oriented_zone()이 False될 때까지 전진(거리 사전측정 불필요)
        ],
    },
    "narrow_5": {  # bottleneck_2 근처 통로 -- 3번 꺾어서 중앙 열린 공간으로 나옴.
        # narrow_4(중앙 튀어나온 벽 + 위쪽 90도벽, 코너 2개)는 zone 방식으로 안 만들기로 함
        # (2026-08-15 결정) -- 문제가 되는 건 start_zone_1에서 출발하는 경로일 때뿐이라,
        # 아래 START_ZONE_1_DEPARTURE로 미션 시작 시 한 번만 처리하는 게 훨씬 간단함.
        "geometry": {
            # 2026-08-15 실측 시작점 (stddev x=9.3cm/y=7.0cm/yaw=8.2deg)
            "cx": 0.5337560352123113, "cy": -0.3448596267925549, "yaw": -0.11990788131625577,
            "length": 0.10, "width": 0.20,        # 2026-08-15 실측: 세로 10cm, 가로 20cm
        },
        "sequence": [
            ("rotate", -0.11990788131625577),  # 1) 2026-08-15 실측: 시작점 yaw 그대로
            ("straight", 0.06),   # 2) 2026-08-15 실측: 6cm 직진
            ("rotate", 1.504),    # 3) 2026-08-15 실측
            ("straight", 0.5),    # 4) 2026-08-15: 0.5m 직진
            ("rotate", 2.893),    # 5) 2026-08-15 실측 -- 여기서 끝, "중앙 열린 공간" 도달.
                                   # 이 회전 이후 별도 직진 스텝 없이 바로 Nav2로 넘겨서 end_zone_1/2로 감.
        ],
    },
}

# 2026-08-15 추가 -- 나중에 여러 zone을 자동으로 이어붙여 돌릴 때(사람이 매번 python3 실행
# 안 하고, 로봇이 알아서 "지금 narrow_5 안이네" 감지해서 시퀀스 트는 방식으로 갈 때) 대비.
# 지금(각 zone을 사람이 직접 python3로 하나씩 실행하는 방식)은 이 문제 자체가 없음 -- zone을
# 자동으로 계속 스캔하는 게 아니라 사람이 그때그때 골라서 트니까. 나중에 자동 연쇄 실행으로
# 바꿀 때, 방금 끝낸 zone 바로 옆(narrow_5 끝나는 지점이 narrow_4 안이거나 인접한 경우처럼)에서
# 재트리거되는 걸 막기 위한 쿨다운 가드 -- VLM_COOLDOWN_SEC(orchestrate_live_teleop.py)와
# 같은 원리.
ZONE_COOLDOWN_SEC = 3.0
_zone_cooldown_state: dict[str, float] = {"last_zone": None, "completed_at": 0.0}


def zone_ready_to_trigger(zone_name: str) -> bool:
    """자동 연쇄 실행 시나리오에서 쓸 것 -- 방금 막 끝낸 zone은 ZONE_COOLDOWN_SEC 동안
    다시 안 걸리게. 지금(수동 실행) 흐름에서는 굳이 안 써도 됨."""
    if _zone_cooldown_state["last_zone"] == zone_name:
        elapsed = time.time() - _zone_cooldown_state["completed_at"]
        if elapsed < ZONE_COOLDOWN_SEC:
            return False
    return True


def mark_zone_completed(zone_name: str) -> None:
    _zone_cooldown_state["last_zone"] = zone_name
    _zone_cooldown_state["completed_at"] = time.time()


# ============================================================
# start_zone_1/2 출발 전용 -- narrow_4(코너 2개) 문제를 zone/시퀀스로 안 풀고, 미션 시작
# 시점에 한 번만 처리. start_zone에서 출발하는 경로만 narrow_4를 지나가야 해서
# 생기는 문제이므로, 회전 없이(= start_zone에 저장된 yaw로 이미 정렬돼있다고 가정)
# 정해진 거리만 먼저 직진시켜서 narrow_4 구간을 통째로 빠져나간 뒤 Nav2로 넘김.
# 2026-08-15: start_zone_1에서 실측한 0.7m가 start_zone_2에도 동일하게 적용된다고 보고 재사용.
# ============================================================
START_ZONES = {
    "start_zone_1": (0.171, 0.202),   # fms_feature_points.jsonl 저장값
    "start_zone_2": (0.076, -0.013),  # fms_feature_points.jsonl 저장값
}
START_ZONE_TRIGGER_RADIUS = 0.3   # 이 반경 안에서 출발하면 아래 처리 적용
START_ZONE_DEPART_DISTANCE = 0.7  # 2026-08-15 실측(start_zone_1 기준): narrow_4 벗어나려면 약 70cm 직진 필요
# (2026-08-15) 직진 후 회전+후진도 추가했다가, 그냥 직진 0.7m만으로 충분하다고 판단해 폐기함.


def near_start_zone(x: float, y: float) -> str | None:
    """가까운 start_zone 이름을 반환(없으면 None)."""
    for name, (zx, zy) in START_ZONES.items():
        if math.hypot(x - zx, y - zy) <= START_ZONE_TRIGGER_RADIUS:
            return name
    return None


def depart_from_start_zone_1(node: Node, buf: Buffer, pub) -> bool:
    """미션 시작 직후 한 번만 호출. start_zone_1/2 근처가 아니면 아무것도 안 하고 바로
    통과(False 반환, 호출부는 평소대로 Nav2로 진행하면 됨). 함수명은 호환성 위해 유지."""
    pose = get_pose(buf)
    if pose is None:
        print("!! TF 못 얻음 -- AMCL 수렴 확인 필요")
        return False
    x, y, yaw = pose
    zone = near_start_zone(x, y)
    if zone is None:
        print("start_zone_1/2 근처 아님 -- 평소대로 Nav2 진행")
        return False

    print(f"{zone} 근처에서 출발 감지 ({x:.3f},{y:.3f}) -- "
          f"narrow_4 회피용 직진 {START_ZONE_DEPART_DISTANCE:.2f}m 먼저 실행")
    try:
        if not drive_straight(node, buf, pub, START_ZONE_DEPART_DISTANCE):
            print("!! 직진 타임아웃"); return False
        print("직진 완료 -- 이제 Nav2로 넘기세요")
        return True
    except KeyboardInterrupt:
        pub.publish(Twist())
        print("\nCtrl+C -- 즉시 정지")
        return False
    finally:
        pub.publish(Twist())


def normalize(a: float) -> float:
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def in_oriented_zone(x: float, y: float, geometry: dict) -> bool:
    """로봇 위치를 zone 로컬 프레임(zone 중심이 원점, zone yaw가 x축)으로 변환해서
    직사각형 범위 안에 있는지 체크. 원형(radius) 대신 이걸 쓰는 이유는 -- 통로 진입 방향이
    정해져 있는 좁고 긴 형태라 yaw 맞춘 직사각형이 실제 여유공간과 훨씬 잘 맞음(bottleneck류
    방향 무관 원형 mutex 영역과는 성격이 다름)."""
    dx, dy = x - geometry["cx"], y - geometry["cy"]
    c, s = math.cos(-geometry["yaw"]), math.sin(-geometry["yaw"])
    local_x = dx * c - dy * s   # zone 축 방향(길이 축)
    local_y = dx * s + dy * c   # zone 축에 수직(폭 축)
    return abs(local_x) <= geometry["length"] / 2 and abs(local_y) <= geometry["width"] / 2


def get_pose(buf: Buffer) -> tuple[float, float, float] | None:
    if not buf.can_transform("map", "base_footprint", rclpy.time.Time()):
        return None
    t = buf.lookup_transform("map", "base_footprint", rclpy.time.Time())
    q = t.transform.rotation
    _, _, yaw = euler_from_quaternion([q.x, q.y, q.z, q.w])
    return t.transform.translation.x, t.transform.translation.y, yaw


def navigate_to_pose(
    node: Node,
    action_client: ActionClient,
    x: float,
    y: float,
    yaw: float,
) -> bool:

    print(
        f"[Nav2] 목표 전송: "
        f"x={x:.3f}, y={y:.3f}, yaw={math.degrees(yaw):.1f}deg"
    )

    if not action_client.wait_for_server(timeout_sec=5.0):
        print("!! /navigate_to_pose Action Server 연결 실패")
        return False

    goal = NavigateToPose.Goal()

    goal.pose.header.frame_id = "map"
    goal.pose.header.stamp = node.get_clock().now().to_msg()

    goal.pose.pose.position.x = x
    goal.pose.pose.position.y = y
    goal.pose.pose.position.z = 0.0

    # yaw -> quaternion
    goal.pose.pose.orientation.x = 0.0
    goal.pose.pose.orientation.y = 0.0
    goal.pose.pose.orientation.z = math.sin(yaw / 2.0)
    goal.pose.pose.orientation.w = math.cos(yaw / 2.0)

    send_future = action_client.send_goal_async(goal)

    rclpy.spin_until_future_complete(node, send_future)

    goal_handle = send_future.result()

    if goal_handle is None:
        print("!! Nav2 goal 전송 실패")
        return False

    if not goal_handle.accepted:
        print("!! Nav2 goal 거절됨")
        return False

    print("[Nav2] Goal accepted")

    result_future = goal_handle.get_result_async()

    rclpy.spin_until_future_complete(node, result_future)

    result = result_future.result()

    if result is None:
        print("!! Nav2 결과 없음")
        return False

    if result.status != GoalStatus.STATUS_SUCCEEDED:
        print(f"!! Nav2 실패 status={result.status}")
        return False

    print("[Nav2] Goal reached successfully")
    return True


def set_nav2_goal_tolerance(
    node: Node,
    xy_tolerance: float,
    yaw_tolerance: float,
) -> bool:

    client = node.create_client(
        SetParameters,
        "/controller_server/set_parameters"
    )

    print(
        f"[Nav2 PARAM] "
        f"xy_goal_tolerance={xy_tolerance}, "
        f"yaw_goal_tolerance={yaw_tolerance}"
    )

    if not client.wait_for_service(timeout_sec=5.0):
        print("!! /controller_server/set_parameters 서비스 연결 실패")
        return False

    request = SetParameters.Request()

    request.parameters = [
        Parameter(
            name="general_goal_checker.xy_goal_tolerance",
            value=ParameterValue(
                type=ParameterType.PARAMETER_DOUBLE,
                double_value=xy_tolerance,
            ),
        ),
        Parameter(
            name="general_goal_checker.yaw_goal_tolerance",
            value=ParameterValue(
                type=ParameterType.PARAMETER_DOUBLE,
                double_value=yaw_tolerance,
            ),
        ),
    ]

    future = client.call_async(request)

    rclpy.spin_until_future_complete(node, future)

    response = future.result()

    if response is None:
        print("!! Nav2 parameter 변경 응답 없음")
        return False

    for result in response.results:
        if not result.successful:
            print(
                f"!! 파라미터 변경 실패: "
                f"{result.reason}"
            )
            return False

    print(
        f"[Nav2 PARAM] 변경 완료: "
        f"xy={xy_tolerance}, yaw={yaw_tolerance}"
    )

    return True

def prepare_narrow_3(
    node: Node,
    action_client: ActionClient,
) -> bool:

    print("")
    print("======================================")
    print(" narrow_3 진입 준비 시작")
    print("======================================")

    try:
        # =================================================
        # 0. 시작할 때 무조건 일반 Nav2 tolerance로 초기화
        # =================================================
        print("")
        print("[0/3] Nav2 goal tolerance 일반 모드 초기화")

        if not set_nav2_goal_tolerance(
            node,
            xy_tolerance=0.1,
            yaw_tolerance=0.25,
        ):
            print("!! Nav2 기본 tolerance 설정 실패")
            return False

        # =================================================
        # 1. 사전 위치 접근
        # =================================================
        print("")
        print("[1/3] narrow_3 사전 위치로 이동")

        if not navigate_to_pose(
            node,
            action_client,
            NARROW_3_PRE_GOAL["x"],
            NARROW_3_PRE_GOAL["y"],
            NARROW_3_PRE_GOAL["yaw"],
        ):
            print("!! narrow_3 사전 위치 접근 실패")
            return False

        print("[WAIT] 1차 Nav2 도착 후 2초 안정화")
        time.sleep(2.0)

        # =================================================
        # 2. 정밀 tolerance로 변경
        # =================================================
        print("")
        print("[2/3] Nav2 goal tolerance 정밀 모드 변경")

        if not set_nav2_goal_tolerance(
            node,
            xy_tolerance=0.03,
            yaw_tolerance=0.05,
        ):
            print("!! Nav2 tolerance 변경 실패")
            return False

        print("[WAIT] 파라미터 적용 대기 1초")
        time.sleep(1.0)

        # =================================================
        # 3. narrow_3 중심으로 정밀 접근
        # =================================================
        print("")
        print("[3/3] narrow_3 중심으로 정밀 접근")

        if not navigate_to_pose(
            node,
            action_client,
            NARROW_3_FINAL_GOAL["x"],
            NARROW_3_FINAL_GOAL["y"],
            NARROW_3_FINAL_GOAL["yaw"],
        ):
            print("!! narrow_3 최종 접근 실패")
            return False

        print("[WAIT] 최종 Nav2 도착 후 1초 안정화")
        time.sleep(1.0)

        print("")
        print("=== narrow_3 Nav2 접근 완료 ===")
        print("이제 기존 rule-based sequence 시작")
        print("")

        return True

    finally:
        # prepare_narrow_3 자체가 실패해도 무조건 원복
        print("")
        print("[복구] Nav2 goal tolerance -> 0.1 / 0.25")

        set_nav2_goal_tolerance(
            node,
            xy_tolerance=0.1,
            yaw_tolerance=0.25,
        )


def rotate_to_yaw(node: Node, buf: Buffer, pub, target_yaw: float,
                   timeout: float = 15.0) -> bool:
    """제자리 회전만(직진 성분 없음) -- target_yaw에 수렴할 때까지."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.05)
        pose = get_pose(buf)
        if pose is None:
            continue
        _, _, yaw = pose
        err = normalize(target_yaw - yaw)
        if abs(err) < YAW_TOL:
            pub.publish(Twist())
            return True
        tw = Twist()
        tw.angular.z = max(-MAX_ANG, min(MAX_ANG, 1.2 * err))
        pub.publish(tw)
        time.sleep(0.05)
    pub.publish(Twist())
    return False


def drive_straight(node: Node, buf: Buffer, pub, distance: float,
                    timeout: float = 20.0) -> bool:
    """distance>0=전진, distance<0=후진. 회전 성분 없이 현재 yaw 방향으로만 직선 이동
    (이 함수 호출 전에 rotate_to_yaw로 방향을 먼저 맞춰뒀다고 가정)."""
    start = get_pose(buf)
    if start is None:
        return False
    sx, sy, _ = start
    sign = 1.0 if distance >= 0 else -1.0
    target_dist = abs(distance)

    deadline = time.time() + timeout
    while time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.05)
        pose = get_pose(buf)
        if pose is None:
            continue
        x, y, _ = pose
        traveled = math.hypot(x - sx, y - sy)
        remaining = target_dist - traveled
        if remaining <= POS_TOL:
            pub.publish(Twist())
            return True
        tw = Twist()
        tw.linear.x = sign * max(0.0, min(MAX_LIN, 0.6 * remaining))
        pub.publish(tw)
        time.sleep(0.05)
    pub.publish(Twist())
    return False


def drive_until_outside_zone(node: Node, buf: Buffer, pub, geometry: dict,
                              timeout: float = 30.0) -> bool:
    """distance를 미리 재지 않고, 현재 yaw 방향으로 전진하면서 in_oriented_zone()이
    False가 될 때(= zone 사각형을 완전히 벗어날 때)까지 계속 감. 출고(exit) 마지막 스텝용."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.05)
        pose = get_pose(buf)
        if pose is None:
            continue
        x, y, _ = pose
        if not in_oriented_zone(x, y, geometry):
            pub.publish(Twist())
            return True
        tw = Twist()
        tw.linear.x = MAX_LIN
        pub.publish(tw)
        time.sleep(0.05)
    pub.publish(Twist())
    return False


def run_zone_sequence(node: Node, buf: Buffer, pub, zone_name: str, exit: bool = False) -> bool:
    if zone_name not in ZONES:
        print(f"!! 알 수 없는 zone: {zone_name} (가능: {list(ZONES)})")
        return False
    cfg = ZONES[zone_name]
    geometry = cfg["geometry"]
    sequence = cfg.get("sequence_exit", cfg["sequence"]) if exit else cfg["sequence"]
    mode = "출고" if exit else "입고"

    pose = get_pose(buf)
    if pose is None:
        print("!! TF 못 얻음 -- AMCL 수렴 확인 필요")
        return False
    x, y, yaw = pose
    print(f"현재 위치: ({x:.3f},{y:.3f}), yaw={math.degrees(yaw):.1f}deg")

    if not in_oriented_zone(x, y, geometry):
        print(f"아직 {zone_name} 영역 밖 -- 시퀀스 시작 안 함(Nav2로 계속 접근하세요)")
        return False

    print(f"=== {zone_name} 영역 진입 확인, {mode} {len(sequence)}단계 시퀀스 시작 ===")
    try:
        for i, (kind, value) in enumerate(sequence, 1):
            if kind == "rotate":
                print(f"{i}) 회전 (target={math.degrees(value):.1f}deg)...")
                if not rotate_to_yaw(node, buf, pub, value):
                    print(f"!! {i}단계 회전 타임아웃"); return False
            elif kind == "straight":
                direction = "전진" if value >= 0 else "후진"
                print(f"{i}) {direction} {abs(value):.2f}m...")
                if not drive_straight(node, buf, pub, value):
                    print(f"!! {i}단계 {direction} 타임아웃"); return False
            elif kind == "exit_zone":
                print(f"{i}) zone 벗어날 때까지 전진...")
                if not drive_until_outside_zone(node, buf, pub, geometry):
                    print(f"!! {i}단계 exit_zone 타임아웃"); return False
            else:
                print(f"!! 알 수 없는 스텝 종류: {kind}"); return False

        print(f"=== {zone_name} 시퀀스 완료 ===")
        return True
    except KeyboardInterrupt:
        pub.publish(Twist())
        print("\nCtrl+C -- 즉시 정지")
        return False
    finally:
        pub.publish(Twist())


def main() -> None:
    valid = list(ZONES) + [z + "_exit" for z in ZONES] + ["depart"]
    if len(sys.argv) < 2 or sys.argv[1] not in valid:
        print(f"사용법: python3 {sys.argv[0]} <zone_name|zone_name_exit|depart>  (가능: {valid})")
        print("  depart: start_zone_1 근처면 narrow_4 회피용 직진 후 Nav2로 넘김")
        print("  <zone_name>_exit: 물품 적재 후 존을 빠져나가는 출고 시퀀스(sequence_exit) 실행")
        sys.exit(1)
    target = sys.argv[1]
    exit_mode = target.endswith("_exit") and target[:-len("_exit")] in ZONES
    if exit_mode:
        target = target[:-len("_exit")]

    rclpy.init()
    node = Node("narrow_rule_based_docking")

    buf = Buffer()
    listener = TransformListener(buf, node)

    print("TF 대기 중...")
    deadline = time.time() + 5.0

    while time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)

        if buf.can_transform(
            "map",
            "base_footprint",
            rclpy.time.Time()
        ):
            print("TF 준비 완료")
            break
    else:
        print("!! TF 못 얻음")
        return
    
    
    # TF 버퍼 채우기(최소 몇 번은 spin 필요, 단발성 sleep으론 안 채워짐)
    for _ in range(20):
        rclpy.spin_once(node, timeout_sec=0.1)

    pub = node.create_publisher(Twist, "/cmd_vel", 10)

    # Nav2 NavigateToPose Action Client
    nav_client = ActionClient(
        node,
        NavigateToPose,
        "/navigate_to_pose"
    )

    # TF 버퍼 채우기
    for _ in range(20):
        rclpy.spin_once(node, timeout_sec=0.1)

    if target == "depart":

        depart_from_start_zone_1(node, buf, pub)

    elif target == "narrow_3" and not exit_mode:

        # =============================================
        # narrow_3만 특별 처리
        #
        # 1. (0.8198, -1.1893)까지 Nav2
        # 2. tolerance 0.03 / 0.05 변경
        # 3. (0.9198, -1.1893)까지 Nav2
        # 4. 기존 narrow_3 sequence 실행
        # =============================================

        if prepare_narrow_3(node, nav_client):

            success = run_zone_sequence(
                node,
                buf,
                pub,
                "narrow_3",
                exit=False
            )

            if not success:
                print("!! narrow_3 시퀀스 실패")

        else:
            print("!! narrow_3 준비 실패 -- 시퀀스 실행하지 않음")

    else:

        # narrow_1 / narrow_2 / narrow_5 / *_exit
        # 기존 동작 그대로
        run_zone_sequence(
            node,
            buf,
            pub,
            target,
            exit=exit_mode
        )

    pub.publish(Twist())

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
