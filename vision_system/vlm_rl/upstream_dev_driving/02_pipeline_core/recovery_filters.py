"""
recovery_filters.py

Trihouse VLM+RL 복구 아키텍처 §7 "후보 0~6단계 필터" 스켈레톤.

설계 원칙 (문서 그대로):
- 위험을 점수로 상쇄하지 않는다. hard violation은 즉시 탈락.
- 0~3단계: 후보 "생성 시점" 검사 (각 후보마다 개별 실행)
- 4~5단계: 모든 후보의 "가상 rollout" 검사 (6C-Lite 붙기 전 자리, 지금은 stub)
- 6단계: 우승 좌표 "단 하나"에 대한 실행 직전 재검사

지금 미구현 상태:
- Memory(Reference/Episodic, DB)가 아직 없어서 3단계(Critical Memory veto)는
  항상 PASS로 반환하는 stub. DB 연결되면 memory_client 부분만 실제 구현으로 교체.
- 4~5단계 rollout도 실제 6C-Lite(world-model ensemble) 붙기 전이라
  현재 코드로 확인 가능한 정적 조건만 검사하는 축소판.
- 이 모듈은 정책 좌표를 안전하게 통과/차단만 판단한다. 실제 /cmd_vel 발행이나
  Nav2 goal 전송은 이 모듈이 하지 않는다 (§1 "VLM/RL은 /cmd_vel을 직접 내지 않는다").
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional
import math
import time


# ----------------------------------------------------------------------
# 데이터 구조
# ----------------------------------------------------------------------

class FilterStage(Enum):
    R0_ROBOT_SENSOR = 0
    R1_CANDIDATE_FORMAT = 1
    R2_TARGET_POSE = 2
    R3_CRITICAL_MEMORY = 3
    R4_NAV2_FEASIBILITY = 4
    R5_FULL_PATH = 5
    R6_FINAL_RECHECK = 6


@dataclass
class RuleResult:
    rule_id: str
    passed: bool
    reason: str = ""


@dataclass
class StageResult:
    stage: FilterStage
    passed: bool
    rules: list[RuleResult] = field(default_factory=list)

    def failed_rules(self) -> list[RuleResult]:
        return [r for r in self.rules if not r.passed]


@dataclass
class SensorSnapshot:
    """R0-03/04: 동기화된 최신 센서 상태. 실제로는 카메라/LiDAR/pose/costmap을
    타임스탬프로 묶어서 만든다 (지금은 필요한 필드만 stub).

    2026-08-08 확인: pinky_pro의 실제 Nav2 스택(bringup_launch.xml)에는
    nav2_collision_monitor가 launch되지 않는다. 즉 bumper/e-stop/Safety
    Supervisor에 해당하는 ROS 노드가 지금 시스템에 존재하지 않는다.

    그래서 아래 세 필드는 기본값을 True가 아니라 False로 둔다.
    실제 하드웨어 토픽(bumper, e-stop)에 연결되기 전까지는 "안전하다"고
    가정하지 않고 "확인 안 됨 = 안전하지 않음"으로 fail-closed 처리한다.
    True로 바꾸는 건 실제 토픽 구독 코드가 값을 채워 넣을 때만 해야 한다.
    """
    timestamp: float
    rgb_ok: bool = True
    seg_ok: bool = True
    lidar_ok: bool = True
    pose_ok: bool = True
    costmap_ok: bool = True
    pose_covariance_ok: bool = True
    bumper_ok: bool = False       # TODO: 실제 bumper 토픽 없음. 물리 하드웨어 붙기 전엔 False 유지
    estop_ok: bool = False        # TODO: 실제 e-stop 신호 없음. 사람이 물리 버튼으로 대체 중
    safety_supervisor_ok: bool = False  # TODO: Safety Supervisor 노드 자체가 아직 없음
    gpu_budget_remaining_s: float = 1.0
    max_staleness_s: float = 0.3

    def is_stale(self, now: float) -> bool:
        return (now - self.timestamp) > self.max_staleness_s


@dataclass
class RobotState:
    """R0-01/02: 로봇이 실제로 정지했고 이전 goal이 정리됐는지."""
    linear_speed: float
    angular_speed: float
    stop_speed_threshold: float = 0.02
    prior_goal_cancel_acked: bool = False


@dataclass
class RecoveryEnvelope:
    """복구가 벗어나면 안 되는 좁은 구역. 문서 §3/§7의 Recovery Envelope."""
    center_x: float
    center_y: float
    radius_m: float
    max_path_length_m: float
    epoch: int


# 2026-08-08 확인: pinky_navigation/params/nav2_params.yaml (velocity_smoother)
# max_velocity: [0.25, 0.0, 1.5] -> 선속도 상한 0.25 m/s가 이미 Nav2 레벨에 있다.
# controller_server의 allow_reversing: false -> 후진 후보는 애초에 Nav2가 못 따라간다.
PINKY_MAX_LINEAR_VEL_MPS = 0.25
PINKY_ALLOW_REVERSING = False
# nav2_params.yaml velocity_smoother: max_decel: [-2.5, 0.0, -3.2] -> 선속도 감속 한계
PINKY_MAX_LINEAR_DECEL_MPS2 = 2.5


def compute_min_stopping_distance_m(
    v_mps: float = PINKY_MAX_LINEAR_VEL_MPS,
    decel_mps2: float = PINKY_MAX_LINEAR_DECEL_MPS2,
) -> float:
    """R2-07/R5-05용 실제 물리 공식: v^2 / (2a). 최고 속도(0.25 m/s)로 달리다가
    최대 감속(2.5 m/s^2)으로 설 때 필요한 최소 거리. 실측이 아니라 이론값이므로
    실제 배포 전 로봇으로 직접 측정해 여유(margin)를 더해야 한다."""
    return (v_mps ** 2) / (2 * decel_mps2)


# 이론상 필요한 최소 정지거리. 0.25 m/s 기준 약 1.25cm -- 매우 작지만, 실제로는
# 센서 지연(R0-03 staleness)과 통신 지연이 더해지므로 여기에 반드시 margin을 더해야 한다.
PINKY_THEORETICAL_STOPPING_DISTANCE_M = compute_min_stopping_distance_m()


@dataclass
class Candidate:
    """TGRPO/SAC가 낸 좌표 후보 (§6). x,y,yaw는 map frame 기준."""
    candidate_id: str
    x: float
    y: float
    yaw: float
    map_frame: str
    map_revision: str
    footprint_class: str
    source_episode_id: Optional[str]
    source_policy_bundle: Optional[str]
    policy_epoch: int
    is_stable_bundle: bool
    timestamp: float


@dataclass
class FilterContext:
    """0~6단계 실행에 필요한 외부 의존성. 실제 배선 전까지는 stub 콜백을 넣는다."""
    current_epoch: int
    current_map_revision: str
    current_footprint_class: str
    envelope: RecoveryEnvelope
    robot_pose_x: float = 0.0
    robot_pose_y: float = 0.0
    robot_pose_yaw: float = 0.0

    # ---- 아래는 실제 시스템과 연결될 자리 (지금은 전부 stub) ----
    query_costmap_free: Callable[[float, float], bool] = lambda x, y: True
    query_footprint_fits: Callable[[float, float, float], bool] = lambda x, y, yaw: True
    query_keepout_violation: Callable[[float, float], bool] = lambda x, y: False
    query_stopping_distance_ok: Callable[[float, float], bool] = lambda x, y: True
    query_memory_critical_veto: Callable[[float, float], Optional[str]] = lambda x, y: None
    query_reference_node_active: Callable[[str], bool] = lambda ep_id: True
    query_nav2_path_feasible: Callable[[float, float, float], bool] = lambda x, y, yaw: True
    query_human_occupied_region: Callable[[float, float], bool] = lambda x, y: False


# ----------------------------------------------------------------------
# 0단계: 로봇·센서 상태 검사
# ----------------------------------------------------------------------

def stage0_robot_sensor(robot: RobotState, snapshot: SensorSnapshot, now: float) -> StageResult:
    rules = [
        RuleResult("R0-01", robot.linear_speed <= robot.stop_speed_threshold
                   and robot.angular_speed <= robot.stop_speed_threshold,
                   "실제 속도가 0으로 유지되지 않음"),
        RuleResult("R0-02", robot.prior_goal_cancel_acked,
                   "기존 goal cancel ACK 없음"),
        RuleResult("R0-03", not snapshot.is_stale(now),
                   f"snapshot이 오래됨 (staleness > {snapshot.max_staleness_s}s)"),
        RuleResult("R0-04", snapshot.rgb_ok and snapshot.seg_ok and snapshot.lidar_ok
                   and snapshot.pose_ok and snapshot.costmap_ok,
                   "RGB/seg/LiDAR/pose/costmap 중 일부 unavailable"),
        RuleResult("R0-05", snapshot.pose_covariance_ok,
                   "pose covariance/TF jump 비정상"),
        RuleResult("R0-06", snapshot.bumper_ok and snapshot.estop_ok
                   and snapshot.safety_supervisor_ok,
                   "bumper/e-stop/Safety Supervisor 비정상"),
        RuleResult("R0-07", snapshot.gpu_budget_remaining_s > 0,
                   "GPU/deadline 예산 부족"),
    ]
    return StageResult(FilterStage.R0_ROBOT_SENSOR, all(r.passed for r in rules), rules)


# ----------------------------------------------------------------------
# 1단계: 후보 형식·출처 검사
# ----------------------------------------------------------------------

def stage1_candidate_format(cand: Candidate, ctx: FilterContext) -> StageResult:
    finite = all(math.isfinite(v) for v in (cand.x, cand.y, cand.yaw))
    rules = [
        RuleResult("R1-01", finite, "x,y,yaw가 유한값이 아님"),
        RuleResult("R1-02", cand.map_frame is not None and cand.map_frame != "",
                   "map frame 미검증"),
        RuleResult("R1-03", cand.map_revision == ctx.current_map_revision
                   and cand.footprint_class == ctx.current_footprint_class,
                   "map/localization/footprint version 불일치"),
        RuleResult("R1-04", cand.source_episode_id is not None or cand.source_policy_bundle is not None,
                   "출처(episode/policy ID)를 추적할 수 없음"),
        RuleResult("R1-05", cand.is_stable_bundle, "canary/미허가 모델의 후보 (저위험 canary만 허용)"),
        RuleResult("R1-06", cand.policy_epoch == ctx.current_epoch,
                   "현재 epoch의 Recovery Envelope에 결속되지 않음"),
    ]
    return StageResult(FilterStage.R1_CANDIDATE_FORMAT, all(r.passed for r in rules), rules)


# ----------------------------------------------------------------------
# 2단계: 목표 좌표 자체 검사
# ----------------------------------------------------------------------

def stage2_target_pose(cand: Candidate, ctx: FilterContext) -> StageResult:
    env = ctx.envelope
    dist_from_center = math.hypot(cand.x - env.center_x, cand.y - env.center_y)
    in_envelope = dist_from_center <= env.radius_m

    rules = [
        RuleResult("R2-01", in_envelope, "Recovery Envelope 밖"),
        RuleResult("R2-02", ctx.query_costmap_free(cand.x, cand.y), "costmap이 free 아님"),
        RuleResult("R2-03", ctx.query_footprint_fits(cand.x, cand.y, cand.yaw),
                   "전체 footprint가 들어가지 않음"),
        RuleResult("R2-04", not ctx.query_keepout_violation(cand.x, cand.y),
                   "keep-out/human-only/cliff 침범"),
        # R2-05(class별 clearance)는 R2-04와 같은 콜백으로 합쳐 처리 중, 실제 구현 시 분리 권장
        RuleResult("R2-06", True, "yaw 적합성 (stub, 실제 통로/센서 시야 검사 필요)"),
        RuleResult("R2-07", ctx.query_stopping_distance_ok(cand.x, cand.y),
                   "정지 가능 거리 확보 안 됨"),
    ]
    return StageResult(FilterStage.R2_TARGET_POSE, all(r.passed for r in rules), rules)


# ----------------------------------------------------------------------
# 3단계: Critical Memory veto 검사 (DB 없음 -> stub, 항상 PASS)
# ----------------------------------------------------------------------

def stage3_critical_memory_veto(cand: Candidate, ctx: FilterContext) -> StageResult:
    """
    TODO(DB 연결 후 교체): 지금은 Memory API가 없으므로 항상 PASS.
    DB 붙으면 ctx.query_memory_critical_veto(x, y) 가 실제 IncidentFact/ReferenceNode
    조회 결과를 반환하도록 교체하고, 아래 stub 로직을 삭제한다.
    이 stub이 켜져 있는 동안은 "사고 이력 회피"가 전혀 동작하지 않는다는 뜻이므로,
    실제 로봇 운행 시 이 단계에 의존하지 말고 사람이 물리적으로 감독해야 한다.
    """
    veto_reason = ctx.query_memory_critical_veto(cand.x, cand.y)
    human_occupied = ctx.query_human_occupied_region(cand.x, cand.y)

    rules = [
        RuleResult("R3-01/02", veto_reason is None,
                   veto_reason or "collision/emergency 유사 사례 (stub: Memory 미연결로 항상 통과)"),
        RuleResult("R3-03", True, "Boundary margin 검사 (stub)"),
        RuleResult("R3-04", cand.source_episode_id is None
                   or ctx.query_reference_node_active(cand.source_episode_id),
                   "관련 Reference가 ACTIVE 아님"),
        RuleResult("R3-05", not human_occupied,
                   "사람 현재·예측 점유영역 침범"),
        RuleResult("R3-06", True, "unknown occupied 처리 (stub)"),
    ]
    return StageResult(FilterStage.R3_CRITICAL_MEMORY, all(r.passed for r in rules), rules)


# ----------------------------------------------------------------------
# 4단계: Nav2 경로 생성 가능성 검사
# ----------------------------------------------------------------------

def _requires_pure_reverse(robot_x, robot_y, robot_yaw, target_x, target_y) -> bool:
    """target이 로봇 바로 뒤(반경 내)에 있어서 회전으로 해결이 안 되는 극단적 케이스만
    True. 문서의 controller_server는 use_rotate_to_heading=true라 대부분의 후방 목표는
    "제자리 회전 후 전진"으로 처리되지, 실제 후진(allow_reversing=false라 애초에 안 씀)이
    필요한 경우는 target이 로봇 발밑처럼 회전 반경 안쪽에 있을 때뿐이다."""
    dist = math.hypot(target_x - robot_x, target_y - robot_y)
    # footprint 반경(약 0.085m, nav2_params footprint 참고)보다 가까우면 회전으로도
    # 도달 불가 -> 사실상 그 자리에서 후진해야 하는 셈
    return dist < 0.09


def stage4_nav2_feasibility(cand: Candidate, ctx: FilterContext) -> StageResult:
    path_ok = ctx.query_nav2_path_feasible(cand.x, cand.y, cand.yaw)
    dist = math.hypot(cand.x - ctx.envelope.center_x, cand.y - ctx.envelope.center_y)

    needs_reverse = _requires_pure_reverse(
        ctx.robot_pose_x, ctx.robot_pose_y, ctx.robot_pose_yaw, cand.x, cand.y
    )
    reverse_ok = (not needs_reverse) or PINKY_ALLOW_REVERSING

    rules = [
        RuleResult("R4-01/02", path_ok, "현재 costmap/TF로 Nav2 path 생성 불가"),
        RuleResult("R4-03", dist <= ctx.envelope.max_path_length_m,
                   f"길이/detour가 envelope/budget 밖 (Nav2 속도 상한 {PINKY_MAX_LINEAR_VEL_MPS}m/s 기준 소요시간도 함께 고려 필요)"),
        RuleResult("R4-04", reverse_ok,
                   "allow_reversing=false인데 목표가 회전 반경보다 가까워 실질적 후진이 필요함"),
        RuleResult("R4-05", True, "재합류/안전정지 가능성 (stub)"),
    ]
    return StageResult(FilterStage.R4_NAV2_FEASIBILITY, all(r.passed for r in rules), rules)


# ----------------------------------------------------------------------
# 5단계: 전체 경로와 이동 공간 검사 (6C-Lite 붙기 전 축소판)
# ----------------------------------------------------------------------

def stage5_full_path(cand: Candidate, ctx: FilterContext) -> StageResult:
    """
    TODO: 실제로는 §8 6C-Lite (n-step 가상 rollout)의 결과를 받아 판정한다.
    지금은 6C-Lite가 없으므로 R5는 항상 미검증 상태로 두고 FAIL 처리하는 게 안전하다.
    (진행을 막는 쪽으로 fail-closed. 임의로 PASS stub을 넣지 않는다.)
    """
    rules = [
        RuleResult("R5-01..07", False,
                   "6C-Lite 가상 rollout 미구현 -- 전체 경로 검증 불가, fail-closed"),
    ]
    return StageResult(FilterStage.R5_FULL_PATH, False, rules)


# ----------------------------------------------------------------------
# 6단계: 실행 직전 재검사 (우승 좌표 단 하나에 대해서만)
# ----------------------------------------------------------------------

def stage6_final_recheck(
    cand: Candidate,
    ctx: FilterContext,
    snapshot: SensorSnapshot,
    now: float,
    safety_clear: bool,
    result_ttl_s: float,
    result_created_at: float,
) -> StageResult:
    epoch_current = cand.policy_epoch == ctx.current_epoch
    ttl_ok = (now - result_created_at) <= result_ttl_s

    # R6-02: 최신 snapshot으로 2~5 재검사 (5는 stub이라 여기서도 항상 실패하게 됨 -- 의도된 동작)
    recheck2 = stage2_target_pose(cand, ctx)
    recheck3 = stage3_critical_memory_veto(cand, ctx)
    recheck4 = stage4_nav2_feasibility(cand, ctx)
    recheck5 = stage5_full_path(cand, ctx)
    recheck_ok = recheck2.passed and recheck3.passed and recheck4.passed and recheck5.passed

    rules = [
        RuleResult("R6-01", epoch_current, "후보/센서/goal epoch가 현재와 다름"),
        RuleResult("R6-02", recheck_ok, "최신 snapshot으로 2~5 재검사 실패"),
        RuleResult("R6-03", True, "우승 좌표/authorized goal 각 1개 (호출부에서 보장)"),
        RuleResult("R6-04", safety_clear, "Safety Supervisor clear 아님"),
        RuleResult("R6-05", ttl_ok and not snapshot.is_stale(now),
                   "absolute deadline 또는 결과 TTL 초과"),
        RuleResult("R6-06", True, "audit log 기록 (호출부 책임, 여기선 stub)"),
    ]
    return StageResult(FilterStage.R6_FINAL_RECHECK, all(r.passed for r in rules), rules)


# ----------------------------------------------------------------------
# 오케스트레이터
# ----------------------------------------------------------------------

@dataclass
class FilterReport:
    candidate_id: str
    passed: bool
    stage_results: list[StageResult]

    def summary(self) -> str:
        lines = [f"[{self.candidate_id}] {'PASS' if self.passed else 'FAIL'}"]
        for sr in self.stage_results:
            mark = "OK " if sr.passed else "X  "
            lines.append(f"  {mark}{sr.stage.name}")
            for fr in sr.failed_rules():
                lines.append(f"       - {fr.rule_id}: {fr.reason}")
        return "\n".join(lines)


def run_generation_filters(
    candidates: list[Candidate],
    robot: RobotState,
    snapshot: SensorSnapshot,
    ctx: FilterContext,
    now: Optional[float] = None,
) -> list[FilterReport]:
    """0~3단계: 각 후보 생성 시점에 실행. 하나라도 실패하면 그 후보는 tournament에 안 올라간다."""
    now = now if now is not None else time.time()
    reports = []
    for cand in candidates:
        s0 = stage0_robot_sensor(robot, snapshot, now)
        s1 = stage1_candidate_format(cand, ctx) if s0.passed else None
        s2 = stage2_target_pose(cand, ctx) if s1 and s1.passed else None
        s3 = stage3_critical_memory_veto(cand, ctx) if s2 and s2.passed else None

        stages = [s for s in (s0, s1, s2, s3) if s is not None]
        passed = all(s.passed for s in stages) and len(stages) == 4
        reports.append(FilterReport(cand.candidate_id, passed, stages))
    return reports


def run_rollout_filters(candidates: list[Candidate], ctx: FilterContext) -> list[FilterReport]:
    """4~5단계: 0~3 통과한 후보만 대상. 지금은 5단계가 항상 FAIL(fail-closed)이므로
    이 함수를 통과하는 후보는 없다 -- 6C-Lite 붙기 전까지는 의도된 동작."""
    reports = []
    for cand in candidates:
        s4 = stage4_nav2_feasibility(cand, ctx)
        s5 = stage5_full_path(cand, ctx) if s4.passed else None
        stages = [s for s in (s4, s5) if s is not None]
        passed = all(s.passed for s in stages) and s5 is not None
        reports.append(FilterReport(cand.candidate_id, passed, stages))
    return reports


def run_final_recheck(
    winner: Candidate,
    ctx: FilterContext,
    snapshot: SensorSnapshot,
    safety_clear: bool,
    result_ttl_s: float,
    result_created_at: float,
    now: Optional[float] = None,
) -> FilterReport:
    """6단계: tournament 우승 좌표 단 하나에 대해서만 실행."""
    now = now if now is not None else time.time()
    s6 = stage6_final_recheck(winner, ctx, snapshot, now, safety_clear, result_ttl_s, result_created_at)
    return FilterReport(winner.candidate_id, s6.passed, [s6])


if __name__ == "__main__":
    env = RecoveryEnvelope(center_x=0.0, center_y=0.0, radius_m=1.5, max_path_length_m=2.0, epoch=1)
    ctx = FilterContext(
        current_epoch=1,
        current_map_revision="rev_001",
        current_footprint_class="pinky_default",
        envelope=env,
        robot_pose_x=0.0, robot_pose_y=0.0, robot_pose_yaw=0.0,
    )
    robot = RobotState(linear_speed=0.0, angular_speed=0.0, prior_goal_cancel_acked=True)
    cand = Candidate(
        candidate_id="cand_0",
        x=0.3, y=0.0, yaw=0.0,
        map_frame="map", map_revision="rev_001", footprint_class="pinky_default",
        source_episode_id=None, source_policy_bundle="bundle_v1",
        policy_epoch=1, is_stable_bundle=True, timestamp=time.time(),
    )

    print("=== 케이스 1: 하드웨어 미연결 기본값 (bumper/estop/safety 전부 False) ===")
    snap_default = SensorSnapshot(timestamp=time.time())
    for r in run_generation_filters([cand], robot, snap_default, ctx):
        print(r.summary())
    print("  -> R0-06에서 반드시 막혀야 정상입니다. 통과하면 fail-closed가 깨진 것.\n")

    print("=== 케이스 2: 실제 bumper/e-stop 토픽 연결됐다고 가정 ===")
    snap_wired = SensorSnapshot(timestamp=time.time(), bumper_ok=True, estop_ok=True, safety_supervisor_ok=True)
    for r in run_generation_filters([cand], robot, snap_wired, ctx):
        print(r.summary())

    rollout_reports = run_rollout_filters([cand], ctx)
    for r in rollout_reports:
        print(r.summary())
        print("  -> 5단계는 6C-Lite 붙기 전까지 항상 FAIL, 의도된 동작입니다.")

    print(f"\n이론적 최소 정지거리(margin 미포함): {PINKY_THEORETICAL_STOPPING_DISTANCE_M*100:.2f} cm")
