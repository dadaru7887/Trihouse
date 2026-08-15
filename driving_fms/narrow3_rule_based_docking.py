"""narrow_1/2/3(상온/냉장/냉동) 전용 -- Nav2/RPP 대신 직접 cmd_vel로 좁은 코너 진입 처리.
오늘 밤 여러 파라미터(inflation/lookahead/rotate_to_heading/allow_reversing)를 다 시도해도
RPP가 냉동구역(narrow_3) 코너에서 계속 collision ahead로 막혀서, 이런 좁은 구간만 규칙
기반으로 우회하기로 결정한 것. `replay_trajectory.py`(사람이 teleop으로 시연한 궤적 재생)와
같은 원칙(costmap collision-check 없이 직접 cmd_vel) 재사용, 대신 "시연"이 아니라 zone마다
필요한 스텝 수가 다른 **명시적 시퀀스**로 구조화한 버전.

zone마다 스텝 구성이 다름(오늘 사진 기준):
- narrow_1(상온), narrow_2(냉장): 진입이 비교적 직선이라 [회전 -> 후진] 2단계면 충분해 보임
- narrow_3(냉동): 코너를 끼고 도는 진입이라 [회전 -> 직진 -> 회전 -> 후진] 4단계 필요

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

MAX_LIN = 0.06
MAX_ANG = 0.5
YAW_TOL = 0.05
POS_TOL = 0.02

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
            "cx": 0.0, "cy": 0.0, "yaw": 0.0,     # TODO: 실측값
            "length": 0.4, "width": 0.3,          # TODO: 실측값
        },
        "sequence": [
            ("rotate", 0.0),     # TODO: 1) 주차 방향(ArUco 보는 방향과 동일하다고 가정, 다르면 분리)
            ("straight", -0.15),  # TODO: 2) 후진 거리(음수)
        ],
    },
    "narrow_2": {  # 냉장
        "geometry": {
            "cx": 0.0, "cy": 0.0, "yaw": 0.0,     # TODO: 실측값
            "length": 0.4, "width": 0.3,          # TODO: 실측값
        },
        "sequence": [
            ("rotate", 0.0),      # TODO
            ("straight", -0.15),  # TODO
        ],
    },
    "narrow_3": {  # 냉동 -- 오늘 씨름했던 코너, 4단계 필요
        "geometry": {
            "cx": 0.0, "cy": 0.0, "yaw": 0.0,     # TODO: 실측값
            "length": 0.5, "width": 0.3,          # TODO: 실측값
        },
        "sequence": [
            ("rotate", -1.408),   # TODO: 1) ArUco 방향(sub_sub_midgoal_3 저장 yaw 참고값)
            ("straight", 0.3),    # TODO: 2) 직진 거리
            ("rotate", -1.408),   # TODO: 3) 주차 방향(1번과 다를 수 있음, "그 주차장의 yaw")
            ("straight", -0.15),  # TODO: 4) 후진 거리(음수)
        ],
    },
    "narrow_5": {  # bottleneck_2 근처 통로 -- 3번 꺾어서 중앙 열린 공간으로 나옴.
        # narrow_4(중앙 튀어나온 벽 + 위쪽 90도벽, 코너 2개)는 zone 방식으로 안 만들기로 함
        # (2026-08-15 결정) -- 문제가 되는 건 start_zone_1에서 출발하는 경로일 때뿐이라,
        # 아래 START_ZONE_1_DEPARTURE로 미션 시작 시 한 번만 처리하는 게 훨씬 간단함.
        "geometry": {
            "cx": 0.0, "cy": 0.0, "yaw": 0.0,     # TODO: 실측값
            "length": 0.8, "width": 0.3,          # TODO: 실측값 (3번 꺾이는 구간 전체 길이)
        },
        "sequence": [
            ("rotate", 0.0),      # TODO: 1)
            ("straight", 0.2),    # TODO: 2)
            ("rotate", 0.0),      # TODO: 3)
            ("straight", 0.2),    # TODO: 4)
            ("rotate", 0.0),      # TODO: 5)
            ("straight", 0.2),    # TODO: 6) -- 이 마지막 지점이 "중앙 열린 공간"에 해당해야 함,
                                   # 여기서 끝나면 이후 Nav2가 이어받아 end_zone_1/2로 감(별도 스크립트 필요 없음)
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
# start_zone_1 출발 전용 -- narrow_4(코너 2개) 문제를 zone/시퀀스로 안 풀고, 미션 시작
# 시점에 한 번만 처리. start_zone_1에서 출발하는 경로만 narrow_4를 지나가야 해서
# 생기는 문제이므로, 회전 없이(= start_zone_1에 저장된 yaw로 이미 정렬돼있다고 가정)
# 정해진 거리만 먼저 직진시켜서 narrow_4 구간을 통째로 빠져나간 뒤 Nav2로 넘김.
# ============================================================
START_ZONE_1 = (0.171, 0.202)   # fms_feature_points.jsonl 저장값
START_ZONE_1_TRIGGER_RADIUS = 0.3   # 이 반경 안에서 출발하면 아래 처리 적용
START_ZONE_1_DEPART_DISTANCE = 0.5  # TODO: 실측값 -- narrow_4 구간을 벗어나는 데 필요한 직진 거리


def near_start_zone_1(x: float, y: float) -> bool:
    return math.hypot(x - START_ZONE_1[0], y - START_ZONE_1[1]) <= START_ZONE_1_TRIGGER_RADIUS


def depart_from_start_zone_1(node: Node, buf: Buffer, pub) -> bool:
    """미션 시작 직후 한 번만 호출. start_zone_1 근처가 아니면 아무것도 안 하고 바로
    통과(False 반환, 호출부는 평소대로 Nav2로 진행하면 됨)."""
    pose = get_pose(buf)
    if pose is None:
        print("!! TF 못 얻음 -- AMCL 수렴 확인 필요")
        return False
    x, y, yaw = pose
    if not near_start_zone_1(x, y):
        print("start_zone_1 근처 아님 -- 평소대로 Nav2 진행")
        return False

    print(f"start_zone_1 근처에서 출발 감지 ({x:.3f},{y:.3f}) -- "
          f"narrow_4 회피용 직진 {START_ZONE_1_DEPART_DISTANCE:.2f}m 먼저 실행")
    try:
        if not drive_straight(node, buf, pub, START_ZONE_1_DEPART_DISTANCE):
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


def run_zone_sequence(node: Node, buf: Buffer, pub, zone_name: str) -> bool:
    if zone_name not in ZONES:
        print(f"!! 알 수 없는 zone: {zone_name} (가능: {list(ZONES)})")
        return False
    cfg = ZONES[zone_name]
    geometry, sequence = cfg["geometry"], cfg["sequence"]

    pose = get_pose(buf)
    if pose is None:
        print("!! TF 못 얻음 -- AMCL 수렴 확인 필요")
        return False
    x, y, yaw = pose
    print(f"현재 위치: ({x:.3f},{y:.3f}), yaw={math.degrees(yaw):.1f}deg")

    if not in_oriented_zone(x, y, geometry):
        print(f"아직 {zone_name} 영역 밖 -- 시퀀스 시작 안 함(Nav2로 계속 접근하세요)")
        return False

    print(f"=== {zone_name} 영역 진입 확인, {len(sequence)}단계 시퀀스 시작 ===")
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
    valid = list(ZONES) + ["depart"]
    if len(sys.argv) < 2 or sys.argv[1] not in valid:
        print(f"사용법: python3 {sys.argv[0]} <zone_name|depart>  (가능: {valid})")
        print("  depart: start_zone_1 근처면 narrow_4 회피용 직진 후 Nav2로 넘김")
        sys.exit(1)
    target = sys.argv[1]

    rclpy.init()
    node = Node("narrow_rule_based_docking")
    buf = Buffer()
    TransformListener(buf, node)
    pub = node.create_publisher(Twist, "/cmd_vel", 10)

    # TF 버퍼 채우기(최소 몇 번은 spin 필요, 단발성 sleep으론 안 채워짐)
    for _ in range(20):
        rclpy.spin_once(node, timeout_sec=0.1)

    if target == "depart":
        depart_from_start_zone_1(node, buf, pub)
    else:
        run_zone_sequence(node, buf, pub, target)

    pub.publish(Twist())
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
