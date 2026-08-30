"""nav_recovery_executor.execute_skill()을 직접 호출하지 않고, 실행 직전에
R2(costmap)+R4(Nav2 경로)+R3-05(사람 veto)를 강제로 거치게 하는 최소 안전 게이트.

전체 R0~R6은 아니다 (R0=하드웨어 없음, R1=형식검사만 생략 가능한 수준이라 스킵,
R3-01/02/03/06=DB 필요, R5=6C-Lite 없음). 그래도 오늘 밤 실제로 검증된 세 개
(R2/R4/R3-05)만이라도 강제로 걸어서, "RL이 뭘 내든 점수로 위험을 못 이긴다"는
원칙의 최소 버전을 지금 바로 실행 경로에 반영한다.

이 게이트가 실제로 위험한 후보를 막는지, 오늘 낮에 시뮬레이션에서 발생한
"Collision Ahead"로 실패했던 REROUTE_RIGHT 케이스로 검증한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from nav2_msgs.action import ComputePathToPose

from nav2_costmap_query import CostmapQueryNode
from human_veto_query import build_human_occupied_query
from nav_recovery_executor import NavRecoveryExecutor, SKILL_NAMES

N_SWEEP_SAMPLES = 5  # 시작점 제외, 목적지까지 등간격으로 몇 점 검사할지

# 학습(데이터 수집) 단계에서는 이 사전체크 게이트를 끄고 Nav2 자체 실시간 안전장치만
# 믿는 쪽으로 결정함 -- 게이트가 근사치라 오탐(costmap 노이즈 등)이 잦아서 탐색 다양성을
# 줄이는 문제가 있었음. 코드는 지우지 않고 남겨둠 -- 실제 배포(학습된 정책이 감독 없이
# 자율로 돌 때) 단계에서는 다시 True로 켜서 마지막 방어선으로 사용할 것.
SAFETY_GATE_ENABLED = False


@dataclass
class SafetyCheckResult:
    passed: bool
    checks: list[tuple[str, bool]]

    def summary(self) -> str:
        lines = [f"{'PASS' if self.passed else 'BLOCKED'}"]
        for name, ok in self.checks:
            lines.append(f"  {'OK ' if ok else 'X  '}{name}")
        return "\n".join(lines)


def _approx_target_pose(skill_id: int, coord, robot_x: float, robot_y: float, robot_yaw: float):
    """skill+coord로 실제로 어디에 도달하게 될지 근사 (nav_recovery_executor의
    execute_skill 내부 매핑과 최대한 맞춤 -- 정밀 기하가 아니라 사전 안전check용 근사)."""
    skill_name = SKILL_NAMES[skill_id]
    if skill_name == "BACKUP":
        dist = math.hypot(coord[0], coord[1])
        return (robot_x - dist * math.cos(robot_yaw), robot_y - dist * math.sin(robot_yaw), robot_yaw)
    if skill_name in ("REROUTE_LEFT", "REROUTE_RIGHT"):
        sign = 1.0 if skill_name == "REROUTE_LEFT" else -1.0
        new_yaw = robot_yaw + sign * abs(float(coord[2]))
        dist = abs(float(coord[0]))
        return (robot_x + dist * math.cos(new_yaw), robot_y + dist * math.sin(new_yaw), new_yaw)
    if skill_name == "REJOIN":
        return (float(coord[0]), float(coord[1]), float(coord[2]))
    # WAIT_REOBSERVE -- 제자리, 이동 없음
    return (robot_x, robot_y, robot_yaw)


def safety_gate(
    costmap_node: CostmapQueryNode,
    skill_id: int,
    coord,
    robot_x: float,
    robot_y: float,
    robot_yaw: float,
    vlm_json: dict | None = None,
) -> SafetyCheckResult:
    skill_name = SKILL_NAMES[skill_id]
    checks: list[tuple[str, bool]] = []

    if not SAFETY_GATE_ENABLED:
        return SafetyCheckResult(True, [("게이트 비활성화 (학습/탐색 모드, Nav2 자체 안전장치만 사용)", True)])

    if skill_name == "WAIT_REOBSERVE":
        # 이동 없음 -- 기하학적 체크 의미 없음, 통과
        return SafetyCheckResult(True, [("WAIT(이동 없음, 기하 체크 생략)", True)])

    target_x, target_y, target_yaw = _approx_target_pose(skill_id, coord, robot_x, robot_y, robot_yaw)

    # 직선 스윕 체크는 "실제로 직선으로 움직이는" 스킬(BACKUP/REROUTE의 DriveOnHeading
    # 구간)에만 맞음 -- REJOIN은 NavigateToPose라서 Nav2가 장애물을 곡선으로 피해갈 수
    # 있는데, 시작점-목적지를 직선으로 가정하고 체크하면 실제로는 안전한 곡선 경로를
    # "직선상에 장애물 있음"으로 잘못 차단하게 됨(실제로 이 문제로 REJOIN이 부당하게
    # 막힌 사례 확인됨, R4-01 실제 Nav2 경로계획은 OK였는데 직선체크만 막았었음).
    # REJOIN은 R4-01(진짜 Nav2 경로계획, 곡선 허용)이 이 역할을 대신하므로 목적지
    # 한 점만 확인.
    straight_line_skill = skill_name in ("BACKUP", "REROUTE_LEFT", "REROUTE_RIGHT")
    n_samples = N_SWEEP_SAMPLES if straight_line_skill else 1

    free = True
    fits = True
    fail_point = None
    for i in range(1, n_samples + 1):
        t = i / n_samples
        sx = robot_x + (target_x - robot_x) * t
        sy = robot_y + (target_y - robot_y) * t
        s_free = costmap_node.query_costmap_free(sx, sy)
        s_fits = costmap_node.query_footprint_fits(sx, sy, target_yaw)
        if not s_free or not s_fits:
            free, fits = s_free, s_fits
            fail_point = (sx, sy)
            break
    if straight_line_skill:
        sweep_label = f"({n_samples}점 스윕, 실패지점={fail_point})" if fail_point else f"({n_samples}점 스윕, 전부 통과)"
    else:
        sweep_label = "(목적지 1점만, 경로는 R4-01이 실제 계획으로 확인)"
    checks.append((f"R2-02 costmap_free {sweep_label}", free))
    checks.append((f"R2-03 footprint_fits {sweep_label}", fits))

    path_ok, error_code = costmap_node.query_nav2_path_feasible_detailed(target_x, target_y, target_yaw)
    if not path_ok and error_code == ComputePathToPose.Result.GOAL_OUTSIDE_MAP and free and fits:
        # 정적 지도(final_map_06)가 실제 공간보다 작아서 생기는 지도 파일 한계일 뿐,
        # "위험하다"는 신호가 아님 -- R2가 이미 실시간 LiDAR(local_costmap)로 그 지점이
        # free하고 footprint도 들어간다는 걸 독립적으로 확인했으므로(추측이 아니라 실측),
        # 이 경우에 한해 R4를 "지도 밖, R2 실측으로 대체"로 통과 처리.
        # (R2 자체가 실패하면(모르는 영역 등) 여기 안 들어오고 그대로 BLOCKED 유지 -- R3-06
        # "모르는 영역은 free로 치지 않는다" 원칙은 그대로 지켜짐)
        checks.append(("R4-01 nav2_path_feasible (지도밖-R2실측대체)", True))
    else:
        checks.append(("R4-01 nav2_path_feasible", path_ok))

    if vlm_json:
        human_query = build_human_occupied_query(vlm_json, robot_x, robot_y, robot_yaw)
        human_clear = not human_query(target_x, target_y)
        checks.append(("R3-05 human_clear", human_clear))

    passed = all(ok for _, ok in checks)
    return SafetyCheckResult(passed, checks)


def safe_execute_skill(
    executor: NavRecoveryExecutor,
    costmap_node: CostmapQueryNode,
    skill_id: int,
    coord,
    robot_x: float,
    robot_y: float,
    robot_yaw: float,
    vlm_json: dict | None = None,
):
    """execute_skill()을 직접 부르지 말고 이 함수를 통해서만 호출할 것.
    반환: (ExecutionResult|None, SafetyCheckResult) -- None이면 게이트에서 막힌 것."""
    gate = safety_gate(costmap_node, skill_id, coord, robot_x, robot_y, robot_yaw, vlm_json)
    if not gate.passed:
        return None, gate
    result = executor.execute_skill(skill_id, coord)
    return result, gate


if __name__ == "__main__":
    """오늘 낮 실제로 실패했던 케이스로 게이트 검증:
    REROUTE_RIGHT, coord=[-0.54966, 0.89369, 0.39273], robot pose=(0.416, 0.214, 0.972)
    실제로는 Nav2가 'Collision Ahead'로 중간에 막았던 케이스 -- 이 게이트가 실행 전에
    미리 걸러내는지 확인 (costmap이 그 방향에 실제로 장애물이 있다고 보는지가 관건)."""
    import rclpy
    import numpy as np

    rclpy.init()
    node = CostmapQueryNode()
    print("costmap 수신 대기...")
    for _ in range(30):
        rclpy.spin_once(node, timeout_sec=0.5)
        if node._local is not None:
            break

    if node._local is None:
        print("!! costmap 못 받음 -- Nav2 sim이 떠있는지 확인 필요")
    else:
        SKILL_ID = SKILL_NAMES.index("REROUTE_RIGHT")
        coord = np.array([-0.54966, 0.89369, 0.39273])
        gate = safety_gate(node, SKILL_ID, coord, robot_x=0.416, robot_y=0.214, robot_yaw=0.972)
        print(f"\n=== 오늘 낮 실패했던 REROUTE_RIGHT 케이스 재검증 ===")
        print(gate.summary())
        print(f"\n-> 게이트가 {'실행 전에 미리 막았음 (원했던 동작)' if not gate.passed else '통과시킴 (Nav2가 나중에 따로 막아야 함)'}")

    node.destroy_node()
    rclpy.shutdown()
