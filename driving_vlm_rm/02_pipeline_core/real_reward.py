"""recovery_data_collector.py의 compute_real_reward(pre_state, post_state, terminal_critical)에
넣을 실측 state를 만드는 헬퍼. 지금까지 dummy/random이던 pre_state/post_state를 실제
odom+LiDAR 기반 값으로 채우기 위함.

주의(정직하게 명시): 이 모듈 자체는 "지금 이 순간의 state 스냅샷 하나"를 만드는 것까지만
한다. pre_state/post_state 한 쌍을 의미있게 채우려면 실제로 recovery 후보가 Nav2로
실행되는 과정이 있어야 함(실행 시작 직전 pre 캡처, 완료 직후 post 캡처) -- 즉 이 모듈은
orchestrate_live_teleop.py의 Watcher(pose+LiDAR)와 향후 nav_recovery_executor.py 연결
지점에서 같이 쓰인다. teleop 관찰만 하는 지금 시점엔 pre/post 쌍을 만들 "실행"이 없어서
당장은 이 함수들을 개별로만 테스트할 수 있음.
"""
from __future__ import annotations

import math
import time
from typing import Optional

from nominal_trajectory import next_nominal_waypoint

# 2026-08-11 밤: 원래 1.0m는 recovery_filters.py의 RecoveryEnvelope 반경(1.5m) 기준으로
# 잡았는데, 실제 라이브 실행(Task #2/#3 첫 성공)에서 이 방(final_map_06, 2.15x2.65m,
# 대각선 ~3.4m) 안에서는 거의 항상 만족되는 값이라 확인됨 -- 실제로 거의 안 움직인
# 경우(progress≈-0.0002)에도 rejoin_bonus(+10.0)가 붙어서 reward가 "얼마나 잘 움직였는지"를
# 잘 못 가림. 0.35m->0.2m도 여전히 넓다고 판단해서 0.15m로 재조정(로봇 footprint 0.12m
# 기준 최소 여유). (2026-08-11 밤 정정: 이 방(final_map_06)이 실제 배포 환경 자체임 --
# "더 큰 창고로 나중에 옮긴다"는 가정이 잘못됐었음, 이 값이 곧 실제 운영 스케일 기준값.)
MISSION_REJOINED_THRESHOLD_M = 0.15

# nav2_costmap_query.py의 FOOTPRINT_INSCRIBED_RADIUS_M(0.06m, footprint 12x12cm 안쪽원
# 반지름)에 센서/제어 오차 여유를 조금 더한 값. 이보다 가까우면 "이미 충돌급"으로 간주.
TERMINAL_CRITICAL_DIST_M = 0.085


def dist_to_goal(robot_x: float, robot_y: float) -> float:
    """nominal_trajectory.py의 다음 waypoint까지 거리. DB Reference Node 없을 때
    goal_pos 자리에 이미 쓰던 것과 동일한 stand-in을 reward 계산에도 재사용."""
    goal = next_nominal_waypoint(robot_x, robot_y)
    return math.hypot(goal["x"] - robot_x, goal["y"] - robot_y)


def is_mission_rejoined(dist_to_goal_m: float) -> bool:
    return dist_to_goal_m < MISSION_REJOINED_THRESHOLD_M


def is_terminal_critical(dist_to_obstacle_m: Optional[float]) -> bool:
    """dist_to_obstacle_m이 None이면(LiDAR 스캔 아직 없음) 안전 쪽으로 판단 -- terminal
    아님으로 취급하지 않고 호출부에서 별도로 '모름' 처리하는 게 맞지만, 여기서는 보수적으로
    False 반환(= 위험 판정 보류). 호출부가 None 여부를 먼저 확인하는 걸 권장."""
    if dist_to_obstacle_m is None:
        return False
    return dist_to_obstacle_m < TERMINAL_CRITICAL_DIST_M


def capture_reward_state(robot_x: float, robot_y: float, lidar_min_range_m: Optional[float],
                          t_reference: Optional[float] = None) -> tuple[dict, bool]:
    """지금 이 순간의 (state dict, terminal_critical) 스냅샷 하나를 만듦.
    recovery_data_collector.compute_real_reward()의 pre_state/post_state 포맷과 호환.

    t_reference: pre_state 캡처 시각(time.time()). 넘기면 elapsed_sec = 지금 - t_reference로
    채움(post_state 캡처용). None이면(pre_state 캡처 시점) elapsed_sec=0.0.

    intervention_level은 Safety Supervisor가 아직 없어서 항상 0.0 -- 가짜 값 넣지 않고
    정직하게 미구현 상태를 반영함 (실제 배포 전 Safety Supervisor 연결되면 교체 필요).
    """
    d_goal = dist_to_goal(robot_x, robot_y)
    terminal_critical = is_terminal_critical(lidar_min_range_m)
    state = {
        "dist_to_goal": d_goal,
        "dist_to_obstacle": lidar_min_range_m if lidar_min_range_m is not None else float("inf"),
        "elapsed_sec": (time.time() - t_reference) if t_reference is not None else 0.0,
        "intervention_level": 0.0,  # TODO(Safety Supervisor 붙으면 실제 값으로 교체)
        "mission_rejoined": is_mission_rejoined(d_goal),
    }
    return state, terminal_critical


if __name__ == "__main__":
    print("=== 테스트 1: 목표에 가까운 정상 상태 ===")
    goal = next_nominal_waypoint(0.6, 0.0)
    print(f"현재 위치 근처 목표 waypoint: {goal}")
    state, crit = capture_reward_state(robot_x=0.6, robot_y=0.0, lidar_min_range_m=0.5)
    print(f"state={state}")
    print(f"terminal_critical={crit}")

    print("\n=== 테스트 2: 오늘 실측한 근접 사례(t=44s, lidar=0.075m) 재현 ===")
    state2, crit2 = capture_reward_state(robot_x=-1.86, robot_y=-0.64, lidar_min_range_m=0.075)
    print(f"state={state2}")
    print(f"terminal_critical={crit2} (True여야 정상 -- 0.075m < {TERMINAL_CRITICAL_DIST_M}m)")

    print("\n=== 테스트 3: LiDAR 스캔 없음(None) ===")
    state3, crit3 = capture_reward_state(robot_x=0.0, robot_y=0.0, lidar_min_range_m=None)
    print(f"state={state3}")
    print(f"terminal_critical={crit3} (False -- '모름'을 위험으로 확정하지 않음, 호출부가 "
          f"dist_to_obstacle==inf인 것 보고 별도 처리 권장)")

    print("\n=== 테스트 4: pre/post 쌍 시뮬레이션(elapsed_sec 확인) ===")
    t_pre = time.time()
    time.sleep(0.3)
    state4, _ = capture_reward_state(robot_x=0.6, robot_y=0.0, lidar_min_range_m=0.5,
                                      t_reference=t_pre)
    print(f"elapsed_sec={state4['elapsed_sec']:.2f} (약 0.3이어야 정상)")
