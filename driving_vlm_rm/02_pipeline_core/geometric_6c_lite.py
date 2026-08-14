"""recovery_filters.py stage5(R5, 6C-Lite/§8)의 최소 기하학적 대체판.

진짜 6C-Lite(학습된 world-model ensemble로 n-step 가상 rollout, 미래 불확실성까지
샘플링)는 아직 없다. 이 모듈은 그 대신, 후보(Candidate)까지 가는 경로를 현재 costmap
스냅샷 기준으로 n개 지점으로 쪼개서 "각 지점이 지금 이 순간 free space인가"만 규칙
기반으로 확인하는 근사판이다.

이 모듈이 못 하는 것 (학습된 world-model과의 진짜 차이):
- 동적 장애물(사람, 다른 로봇)의 미래 움직임을 예측하지 않는다 -- 지금 이 순간의 정적
  스냅샷만 본다. 사람이 걸어오고 있어도 "지금 이 지점이 비어있으면" 통과시킨다.
- 로봇 자신의 미래 위치 불확실성(localization drift, 제어 오차, 바퀴 미끄러짐)을
  모델링하지 않는다. 경로가 이론적으로 free여도 실제로는 오차 때문에 벗어날 수 있다.
- "성공 확률" 같은 확률적 추정을 하지 않는다 -- 이진 pass/fail 판정만 한다.
- 학습 데이터로 개선되지 않는다 -- 규칙은 고정이다.

그래도 없는 것보다 나은 이유: 최소한 "직선/단순 경로 위에 이미 알려진 정적 장애물이
버젓이 있는데도 후보를 통과시켜버리는" 명백한 실수는 막을 수 있다. R0~R4가 후보
좌표 "그 지점 하나"만 보는 것과 달리, 이 모듈은 "거기까지 가는 길" 전체를 본다.

오늘(2026-08-11) 기준 recovery_filters.py에 아직 연결 안 함 -- 모듈만 독립적으로 존재.
연결하려면 stage5_full_path()의 하드코딩된 FAIL을
geometric_rollout_check(cand, ctx.robot_pose_x, ctx.robot_pose_y, ctx.robot_pose_yaw,
                         ctx.query_costmap_free, ctx.query_footprint_fits,
                         ctx.query_keepout_violation)
로 교체하면 된다 (FilterContext의 기존 콜백을 그대로 재사용하도록 설계함 --
nav2_costmap_query.py의 query_costmap_free/query_footprint_fits/query_keepout_violation과
시그니처가 이미 일치함).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

# recovery_filters.py의 기존 타입을 그대로 재사용 (새 타입 체계 안 만듦)
from recovery_filters import Candidate, FilterStage, RuleResult, StageResult

DEFAULT_N_STEPS = 8  # 후보까지 가는 경로를 몇 개 지점으로 쪼갤지
MIN_STEP_SPACING_M = 0.05  # 스텝 간 최소 간격 -- 이보다 촘촘하면 costmap 해상도 대비 의미 없음


@dataclass
class RolloutStep:
    """진단용 -- 어느 지점에서 어떤 이유로 걸렸는지 남기기 위함."""
    step_idx: int
    x: float
    y: float
    yaw: float
    frac: float  # 0.0(시작) ~ 1.0(후보 지점) 사이 진행률
    costmap_free: Optional[bool] = None
    footprint_fits: Optional[bool] = None
    keepout_violation: Optional[bool] = None

    def ok(self) -> bool:
        return bool(self.costmap_free) and bool(self.footprint_fits) and not bool(self.keepout_violation)


def _interpolate_path(start_x: float, start_y: float, start_yaw: float,
                       goal_x: float, goal_y: float, goal_yaw: float,
                       n_steps: int) -> list[tuple[float, float, float, float]]:
    """시작점 제외, 후보 지점 포함한 n_steps개 (x, y, yaw, frac) 리스트.
    직선 보간(단순 기하학) -- 실제 Nav2 경로 곡률은 반영 안 함, 그게 이 모듈의 한계 중 하나."""
    points = []
    for i in range(1, n_steps + 1):
        frac = i / n_steps
        x = start_x + (goal_x - start_x) * frac
        y = start_y + (goal_y - start_y) * frac
        # yaw는 진행 방향 기준으로 선형 보간 (짧은 각도 방향으로)
        dyaw = goal_yaw - start_yaw
        while dyaw > math.pi:
            dyaw -= 2 * math.pi
        while dyaw < -math.pi:
            dyaw += 2 * math.pi
        yaw = start_yaw + dyaw * frac
        points.append((x, y, yaw, frac))
    return points


def geometric_rollout_check(
    cand: Candidate,
    robot_x: float, robot_y: float, robot_yaw: float,
    query_costmap_free: Callable[[float, float], bool],
    query_footprint_fits: Callable[[float, float, float], bool],
    query_keepout_violation: Callable[[float, float], bool],
    n_steps: int = DEFAULT_N_STEPS,
) -> StageResult:
    """R5(6C-Lite) 자리에 꽂는 기하학적 근사 검사.

    현재 로봇 위치 -> 후보 좌표까지 직선을 n_steps개로 쪼개서 각 지점마다
    costmap_free / footprint_fits / keepout_violation을 확인한다.
    하나라도 걸리면 그 즉시 FAIL, 실패한 첫 지점을 근거로 남긴다.
    전부 통과하면 PASS.
    """
    dist = math.hypot(cand.x - robot_x, cand.y - robot_y)
    effective_steps = n_steps
    if dist > 0 and dist / n_steps < MIN_STEP_SPACING_M:
        effective_steps = max(1, int(dist / MIN_STEP_SPACING_M))

    path = _interpolate_path(robot_x, robot_y, robot_yaw, cand.x, cand.y, cand.yaw, effective_steps)

    steps: list[RolloutStep] = []
    first_failure: Optional[RolloutStep] = None
    for i, (x, y, yaw, frac) in enumerate(path):
        step = RolloutStep(step_idx=i, x=x, y=y, yaw=yaw, frac=frac)
        step.costmap_free = query_costmap_free(x, y)
        step.footprint_fits = query_footprint_fits(x, y, yaw)
        step.keepout_violation = query_keepout_violation(x, y)
        steps.append(step)
        if first_failure is None and not step.ok():
            first_failure = step
            break  # 첫 실패 지점에서 바로 중단 (뒤 지점 계속 확인해봐야 의미 없음)

    passed = first_failure is None
    if passed:
        rules = [RuleResult(
            "R5-GEO-01", True,
            f"{effective_steps}스텝 경로 전부 free/footprint_fits/keepout 통과 (기하학적 근사, "
            f"동적 장애물 예측 없음)")]
    else:
        reasons = []
        if not first_failure.costmap_free:
            reasons.append("costmap 점유")
        if not first_failure.footprint_fits:
            reasons.append("footprint 안 들어감")
        if first_failure.keepout_violation:
            reasons.append("keepout 침범")
        rules = [RuleResult(
            "R5-GEO-01", False,
            f"경로의 {first_failure.frac*100:.0f}% 지점(스텝 {first_failure.step_idx+1}/"
            f"{effective_steps}, x={first_failure.x:.2f},y={first_failure.y:.2f})에서 걸림: "
            f"{', '.join(reasons)}")]

    return StageResult(FilterStage.R5_FULL_PATH, passed, rules)


# 2026-08-12 추가: TGRPO의 "live rollout"(N개 후보를 실제/시뮬레이션으로 평가해서 그룹
# advantage를 냄) 자리를 채우기 위한 1단계. 지금 6C-Lite는 pass/fail 이진 판정만 주는데,
# TGRPO가 필요로 하는 건 후보별 reward "값"임 -- 그 갭을 기하학적 근사로 메움.
# **1단계 = 로그/관찰 전용, 아직 gradient update에 안 씀**(사용자 확인, 2026-08-12).
# 이 추정치가 실제 reward(compute_real_reward)와 얼마나 상관관계 있는지 로봇으로 실측
# 검증한 뒤에야 2단계(TGRPO 학습에 실제로 섞기)를 검토할 것 -- 검증 없이 바로 학습에
# 쓰면 근사 공식을 "속이는" 방향으로 정책이 학습될 위험(reward hacking) 있음.
DEFAULT_SPEED_MPS = 0.1  # nav_recovery_executor.py의 DEFAULT_SPEED와 동일값(단일 소스 유지 위해 상수만 복제, import 순환 방지)
MISSION_REJOINED_THRESHOLD_M = 0.15  # real_reward.py의 MISSION_REJOINED_THRESHOLD_M과 동일


def estimate_candidate_reward(
    cand: Candidate,
    robot_x: float, robot_y: float, robot_yaw: float,
    query_costmap_free: Callable[[float, float], bool],
    query_footprint_fits: Callable[[float, float, float], bool],
    query_keepout_violation: Callable[[float, float], bool],
    goal_x: float, goal_y: float,
    n_steps: int = DEFAULT_N_STEPS,
) -> dict:
    """진짜 실행 없이 후보 하나의 reward를 기하학적으로 근사 추정.
    real_reward.py/recovery_data_collector.compute_real_reward()의 가중치를 그대로
    재사용해서 실제 reward와 같은 스케일로 비교 가능하게 함.

    한계(정직하게 명시):
    - clearance_cost는 연속값이 아니라 geometric_rollout_check의 pass/fail 이진 판정으로
      대신함(실패=terminal_critical급 페널티, 통과=0 취급) -- costmap 실제 cost 값 기반
      연속 추정은 다음 개선 과제.
    - intervention_level은 항상 0 (진짜 실행이 아니니 알 수 없음 -- real_reward.py도
      Safety Supervisor 없어서 항상 0인 것과 동일 원칙, 가짜 값 안 넣음).
    - time_cost는 직선거리/DEFAULT_SPEED_MPS 근사(실제 회전/가감속 시간 무시).
    """
    rollout = geometric_rollout_check(
        cand, robot_x, robot_y, robot_yaw,
        query_costmap_free, query_footprint_fits, query_keepout_violation, n_steps,
    )

    dist_to_goal_now = math.hypot(goal_x - robot_x, goal_y - robot_y)
    dist_to_goal_after = math.hypot(goal_x - cand.x, goal_y - cand.y)
    progress_est = dist_to_goal_now - dist_to_goal_after

    if not rollout.passed:
        # 6C-Lite 자체가 "부딪힐 것 같다"고 판단한 경우 -- terminal_critical과 동일 취급
        # (compute_real_reward()도 terminal_critical=True면 -100.0 고정 반환하는 것과 동일 원칙)
        return {
            "estimated_reward": -100.0,
            "estimated_terminal_critical": True,
            "progress_est": progress_est,
            "clearance_cost_est": None,  # 이진 판정이라 연속값 없음(위 한계 참고)
            "rollout_passed": False,
        }

    w_progress, w_time, r_rejoin = 1.0, 0.1, 10.0  # compute_real_reward()와 동일 가중치
    dist_to_candidate = math.hypot(cand.x - robot_x, cand.y - robot_y)
    time_cost_est = dist_to_candidate / DEFAULT_SPEED_MPS
    rejoin_bonus_est = r_rejoin if dist_to_goal_after < MISSION_REJOINED_THRESHOLD_M else 0.0

    estimated_reward = w_progress * progress_est - w_time * time_cost_est + rejoin_bonus_est
    return {
        "estimated_reward": estimated_reward,
        "estimated_terminal_critical": False,
        "progress_est": progress_est,
        "clearance_cost_est": 0.0,  # 통과했으니 0 취급(연속값 아님, 위 한계 참고)
        "rollout_passed": True,
    }


if __name__ == "__main__":
    # 로봇/Nav2 연결 없이 mock 콜백으로 자체 테스트 -- 로직 자체가 맞는지만 확인
    print("=== 테스트 1: 완전히 뚫린 경로 (전부 free) ===")
    cand_clear = Candidate(
        candidate_id="clear", x=1.0, y=0.0, yaw=0.0, map_frame="map", map_revision="rev1",
        footprint_class="pinky_default", source_episode_id=None, source_policy_bundle="b1",
        policy_epoch=1, is_stable_bundle=True, timestamp=0.0,
    )
    result = geometric_rollout_check(
        cand_clear, robot_x=0.0, robot_y=0.0, robot_yaw=0.0,
        query_costmap_free=lambda x, y: True,
        query_footprint_fits=lambda x, y, yaw: True,
        query_keepout_violation=lambda x, y: False,
    )
    print(result.summary() if hasattr(result, "summary") else f"passed={result.passed}, rules={result.rules}")

    print("\n=== 테스트 2: 경로 중간에 장애물 (0.5m 지점부터 막힘) ===")
    def blocked_after_half(x, y):
        return x < 0.5  # 로봇(0,0)->후보(1,0) 직선에서 x=0.5 지점부터 막혔다고 가정
    result2 = geometric_rollout_check(
        cand_clear, robot_x=0.0, robot_y=0.0, robot_yaw=0.0,
        query_costmap_free=blocked_after_half,
        query_footprint_fits=lambda x, y, yaw: True,
        query_keepout_violation=lambda x, y: False,
    )
    print(f"passed={result2.passed}")
    for r in result2.rules:
        print(f"  {r.rule_id}: {'PASS' if r.passed else 'FAIL'} -- {r.reason}")

    print("\n=== 테스트 3: keepout 침범 (도착지점 근처만) ===")
    cand_far = Candidate(
        candidate_id="far", x=2.0, y=0.0, yaw=0.0, map_frame="map", map_revision="rev1",
        footprint_class="pinky_default", source_episode_id=None, source_policy_bundle="b1",
        policy_epoch=1, is_stable_bundle=True, timestamp=0.0,
    )
    result3 = geometric_rollout_check(
        cand_far, robot_x=0.0, robot_y=0.0, robot_yaw=0.0,
        query_costmap_free=lambda x, y: True,
        query_footprint_fits=lambda x, y, yaw: True,
        query_keepout_violation=lambda x, y: x > 1.8,
    )
    print(f"passed={result3.passed}")
    for r in result3.rules:
        print(f"  {r.rule_id}: {'PASS' if r.passed else 'FAIL'} -- {r.reason}")

    print("\n=== 테스트 4: 아주 가까운 후보 (min spacing 로직 확인) ===")
    cand_near = Candidate(
        candidate_id="near", x=0.03, y=0.0, yaw=0.0, map_frame="map", map_revision="rev1",
        footprint_class="pinky_default", source_episode_id=None, source_policy_bundle="b1",
        policy_epoch=1, is_stable_bundle=True, timestamp=0.0,
    )
    result4 = geometric_rollout_check(
        cand_near, robot_x=0.0, robot_y=0.0, robot_yaw=0.0,
        query_costmap_free=lambda x, y: True,
        query_footprint_fits=lambda x, y, yaw: True,
        query_keepout_violation=lambda x, y: False,
    )
    print(f"passed={result4.passed} (아주 가까운 거리라 effective_steps가 줄어들어야 정상)")

    print("\n=== 테스트 5: estimate_candidate_reward (로봇 없이 mock으로 검증) ===")
    print("-- 5a: 뚫린 경로 + 목표에 가까워지는 후보 (progress 양수, rollout 통과 기대) --")
    goal = (2.0, 0.0)
    est_a = estimate_candidate_reward(
        cand_clear, robot_x=0.0, robot_y=0.0, robot_yaw=0.0,
        query_costmap_free=lambda x, y: True,
        query_footprint_fits=lambda x, y, yaw: True,
        query_keepout_violation=lambda x, y: False,
        goal_x=goal[0], goal_y=goal[1],
    )
    print(f"  {est_a}")
    assert est_a["rollout_passed"] is True
    assert est_a["progress_est"] > 0, "목표(2,0)에 더 가까워지는 후보(1,0)라 progress 양수여야 함"

    print("-- 5b: 경로 중간에 장애물 (rollout 실패 -> -100.0 기대) --")
    est_b = estimate_candidate_reward(
        cand_clear, robot_x=0.0, robot_y=0.0, robot_yaw=0.0,
        query_costmap_free=blocked_after_half,
        query_footprint_fits=lambda x, y, yaw: True,
        query_keepout_violation=lambda x, y: False,
        goal_x=goal[0], goal_y=goal[1],
    )
    print(f"  {est_b}")
    assert est_b["rollout_passed"] is False
    assert est_b["estimated_reward"] == -100.0

    print("-- 5c: 목표 바로 그 지점(rejoin_bonus 기대) --")
    cand_at_goal = Candidate(
        candidate_id="at_goal", x=2.0, y=0.0, yaw=0.0, map_frame="map", map_revision="rev1",
        footprint_class="pinky_default", source_episode_id=None, source_policy_bundle="b1",
        policy_epoch=1, is_stable_bundle=True, timestamp=0.0,
    )
    est_c = estimate_candidate_reward(
        cand_at_goal, robot_x=0.0, robot_y=0.0, robot_yaw=0.0,
        query_costmap_free=lambda x, y: True,
        query_footprint_fits=lambda x, y, yaw: True,
        query_keepout_violation=lambda x, y: False,
        goal_x=goal[0], goal_y=goal[1],
    )
    print(f"  {est_c}")
    assert est_c["estimated_reward"] > est_a["estimated_reward"], "목표에 더 가까운 후보가 더 높은 추정 reward여야 함"
    print("\n모든 mock 테스트 통과.")
