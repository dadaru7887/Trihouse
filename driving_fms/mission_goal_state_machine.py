"""FMS 목표 계층 상태머신: Start(start_zone) -> 필요한 적재구역(들) 방문(상온/냉장/냉동)
-> 배송 도착지점(middle_goal) -> End(end_zone) 복귀, 배터리 낮으면 언제든 safe_zone으로 override.

2026-08-12 FMS 손그림(EMS 노트) 기반, 같은 날 여러 차례 정정 거쳐 최종 확정된 구조 반영.
nominal_trajectory.py(7개 waypoint 순서대로 도는 단순 리스트)를 대체하는 용도 -- RL이 보는
인터페이스(next_nominal_waypoint(x,y) -> {id,x,y})는 그대로 유지해서, 이 상태머신이 결정하는
"지금 향해야 할 점 하나"만 RL에 넘어감. FMS 상태 전이 로직 자체는 RL이 몰라도 됨.

**중요 정정 이력 (첫 버전에서 바뀐 것들, 헷갈리지 않게 기록)**:
1. Safe Zone은 좌/우 2개 대칭이 아니라 **1개**(원래는 Start=End=배터리 복귀 지점을 겸했음).
2. "Sub-Sub midgoal"은 병목구간 ArUco 인식 이벤트가 아니라 **상온/냉장/냉동 적재구역 3곳**
   (번호체계: 상온=1, 냉장=2, 냉동=3). ArUco 마커는 각 적재구역 위치 확인용으로 쓰일 수 있지만,
   "병목 통과 = 다음 stage"라는 원래 설계는 틀렸었음.
3. "병목(bottleneck)"은 목표 지점이 아니라 **다중 로봇 상호배제(mutex) 구역**(반경 기반, 방향
   없음) -- 먼저 진입한 로봇이 우선 통과, 나머지는 대기. Stage 흐름과 무관한 별도 개념이라
   FeaturePoint/Stage에서 완전히 분리함(BottleneckZone으로 따로 관리).
4. middle_goal 1/2는 온도구역과 무관하게 그냥 왼쪽부터 번호 매긴 배송 도착지점.
5. **[2026-08-13] Start/End를 Safe Zone에서 완전히 분리함.** 기존엔 "Safe Zone = Start = End =
   배터리 override" 하나로 통합돼 있었는데, 이제 **safe_zone은 배터리 위급 override 전용**으로만
   쓰고, 로봇 출발/복귀는 별도의 start_zone_N/end_zone_N(N=1,2, 로봇/도킹 슬롯별)을 씀. 슬롯별로
   start/end 위치는 서로 다를 수 있고(바구니 때문에 end는 물리적으로 조금 이동 필요), yaw도
   서로 거의 반대 방향(도킹 방향 vs 출발 방향). 새 미션 배정 시 로직은: end_zone에서
   (1)후진 -> (2)제자리에서 같은 슬롯 start_zone의 yaw로 회전 -> (3)그 자리에서 바로 출발
   (start_zone의 좌표로 실제 이동하는 스텝은 없음, yaw만 참조). 이 파일은 그 순서 중 "어느
   좌표/yaw를 참조해야 하는지"만 제공하고, 후진/회전 자체의 실행은 nav_recovery_executor.py쪽
   책임(§ MissionGoalStateMachine.departure_yaw 참고).
6. **[2026-08-13] safe_zone = 공식 스펙의 `RECOVERY_RETURN_<NN>`.** Trihouse RMF waypoint
   가이드(`docs/guideline/waypoint.md`)를 다시 확인하다 발견 -- `RECOVERY_RETURN_<NN>`은
   "비상 해제 후 점검 복귀 지점"으로 `REQUIRE_OPERATOR` 플래그가 붙어있음. 즉 safe_zone
   도착 = 자동 미션 재개가 아니라 **사람이 명시적으로 해제해야 함**. `operator_release()`로
   구현, `set_loading_targets()`가 BATTERY_OVERRIDE 상태에서 직접 호출되는 걸 막아둠. (참고로
   start_zone/end_zone 분리는 이 공식 문서에 대응 개념이 없는 우리 자체 커스텀 -- 팀 확인 완료.)
7. **[2026-08-13] 배터리 override 목적지를 safe_zone 고정에서 "더 가까운 충전 가능 지점"으로
   확장.** safe_zone이 지도상 냉동구역 쪽에 치우쳐있어서(y 크게 음수), 상온/냉장구역 근처에서
   위급해지면 safe_zone까지 멀리 가야 하는 비효율이 있었음. start_zone도 충전 가능하다는
   전제(사용자 확인)로, robot 위치 기준 safe_zone/start_zone 중 유클리드 거리가 더 가까운
   쪽으로 override. **단, operator 게이트는 목적지에 따라 다름**: safe_zone(=RECOVERY_RETURN)
   으로 갔으면 여전히 `operator_release()` 필요, start_zone으로 갔으면 배터리 문제일 뿐이고
   충전소 도착이라 자동재개 허용(사용자 판단, "배터리 문제인데 충전소로 가는 거니까").
   **[미구현, DB 연동 대기]** end_zone_1/2 슬롯 배정(슬롯1 우선, 차있으면 슬롯2, 둘 다 차있으면
   복귀신호 받은 다른 로봇 임시대기)은 다중 로봇 조율이 필요한데, `.23`/`.37`이 서로 다른
   ROS_DOMAIN_ID를 써서 로봇끼리 직접 통신 불가 -- DB/Gateway API 붙으면 그쪽으로 구현 예정
   (지금은 4060 공유파일 같은 임시방편도 고려했으나 사용자가 "나중에 DB가 붙을 것 같다"고
   보류 결정, [[vlm_rl_db_schema_delivered]] 참고).
8. **[2026-08-13] end_zone 슬롯 배정 로직은 미리 짜둠(§ `_resolve_end_target`).** 1번 슬롯
   우선 -> 차있으면 2번 -> 둘 다 차있으면 safe_zone에 임시 정차, 나중에 슬롯 비면 다음
   `current_target()` 호출 때 자동으로 그쪽으로 다시 안내. `occupied_end_slots` 파라미터로
   점유 정보를 주입받는 구조라(DB/관제센터 신호를 여기 그대로 넣으면 됨) 7번 항목의 DB 연동
   대기 상태와 맞물림 -- 지금은 신호가 없어서(`None`) 항상 이 세션 고정 슬롯으로 fallback.
   **이 임시 정차는 배터리 override와 무관**(단순 혼잡 문제라 operator_release() 안 씀).
9. **[2026-08-13] 병목 mutex 로직 인터페이스 구현(§ `bottleneck_should_wait`/
   `bottleneck_should_yield`).** `active_bottleneck()`은 "지금 병목 안에 있는지" 기하 판정만
   하고, 실제 "다른 로봇이 먼저 와있으면 대기" 배타 로직은 이번에 처음 짬. 확정된 규칙:
   - 신호(`occupied_bottlenecks`) 없으면 **보수적으로 대기**(end_zone 슬롯과 달리 병목은
     실제 충돌 위험 구간이라 안전 우선, 낙관적 기본값에서 변경).
   - 단 `battery_critical=True`(배터리 CRITICAL 이하)면 **우선권 점유하고 무조건 통과** --
     탈출경로가 병목 mutex보다 우선. 이미 병목 안에 있는 다른 로봇도 `bottleneck_should_yield()`
     로 "지금 벗어나야 함" 신호를 받을 수 있게 대칭 메서드 추가함(먼저 온 로봇이라도 배터리
     위급 로봇에게 양보).
   - **두 로봇이 동시에 CRITICAL이고 같은 병목을 두고 경쟁하면 배터리 잔량이 더 낮은 쪽이
     우선**으로 결정함(timestamp 기준보다 안전 -- 방전까지 남은 여유를 직접 반영하니까,
     2026-08-13 사용자 확정). 단 극단적 엣지케이스(2대 동시운용+동시 CRITICAL+같은 병목)라
     실제 로직은 아직 미구현 -- `critical_claims` 신호가 각 로봇 배터리 %까지 실어 날라야
     구현 가능해서 신호 스키마 설계(DB/Gateway 연동) 시점에 같이 짤 것.
   - `occupied_bottlenecks`/`critical_claims` 둘 다 DB/Gateway API 연동 전까진 신호 자체가
     없음 -- ROS_DOMAIN_ID 분리로 로봇간 직접 통신도 불가([[vlm_rl_db_schema_delivered]]).
10. **[2026-08-13] 같은 적재구역에 로봇 2대 이상 몰리는 문제 -- `loading_zone_should_wait()`
    추가.** 공식 스펙의 `FROZEN_SAFE_WAIT`/`PACKING_SAFE_WAIT`(적재구역 주변 안전 대기점)와
    같은 문제인데, 새 홀딩포인트 좌표 없이 병목과 같은 신호/판정 패턴만 재사용함(좁은 선반에
    로봇 두 대가 동시에 들어가는 물리적 충돌 위험이 병목이랑 똑같은 성격이라서). 신호 없으면
    보수적으로 대기(병목과 동일 원칙). 배터리 CRITICAL 우선권 예외도 bottleneck_should_wait()와
    동일하게 추가함(일관성 있게 모든 대기 판정에 넣기로 함, 2026-08-13 사용자 결정).
11. **[2026-08-13] middle_goal도 둘 다 막히는 경우 처리 -- `_resolve_middle_goal_target()`.**
    기존엔 `_middle_goal1_available` boolean 하나뿐이라 "1번 안 되면 무조건 2번"이었고 2번도
    막힌 경우를 못 봤음. `set_middle_goal2_available()` 추가하고, 둘 다 안 되면 **그 자리에서
    대기**(로봇 현재 위치를 그대로 목표로 반환 -- end_zone/병목/적재구역처럼 별도 대기
    지점/신호 인터페이스 안 만들고 제일 단순하게, 사용자 결정: "잠시 그 자리에서 멈춰도
    되지 않을까"). 병목/적재구역 대기도 개념적으로 전부 동일("그 자리에서 잠깐 멈춤"), 이
    프로젝트의 모든 혼잡 처리 패턴이 결국 다 이 하나의 아이디어로 수렴함.

**전체 흐름**: start_zone(Start) -> 필요한 적재구역 방문(1개 이상) -> middle_goal(1 우선,
안 되면 2) -> end_zone(End) 복귀. 배터리 위급이면 stage와 무관하게 safe_zone으로 override.

**fms_feature_points.jsonl에서 자동 로드**: label이 safe_zone/start_zone_N/end_zone_N/
sub_sub_midgoal_N/middle_goal_N/bottleneck_N 패턴인 줄을 읽어서 좌표 채움. 없는 지점은 좌표
None으로 남아있고, 실제 목표로 쓰이면 fail-closed(예외) -- battery_watcher.py의 빈
SAFE_ZONE_WAYPOINTS와 같은 원칙.

**2026-08-13 세션 종료 시점 상태(전부 확정)**:
- safe_zone, bottleneck_1/2, middle_goal_1/2, sub_sub_midgoal_1/2/3, start_zone_1/2,
  end_zone_1/2 전부 실측 완료(2026-08-12 값들 중 다수는 이번에 재검증하며 교체됨 -- 특히
  bottleneck_2/middle_goal_1/middle_goal_2/sub_sub_midgoal_3는 기존 값과 30cm~1.4m+ 차이
  발견돼 폐기, `vlm_rl_backup/coord_remeasure_2026-08-13/`에 이전 값 백업됨).
- 각 적재구역 ArUco 마커 ID 전부 확정: 상온(1)=id2, 냉장(2)=id1, 냉동(3)=id0, 전부 DICT_5X5_50
  (aruco_recognition_distance_tests.jsonl 참고).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Optional

FMS_FEATURE_POINTS_PATH = Path(__file__).parent / "fms_feature_points.jsonl"

ZONE_SLOTS = (1, 2)  # start_zone_N/end_zone_N에 쓰이는 도킹 슬롯 번호

# 2026-08-13: confirm_arrival_by_aruco()의 게이트 기준값들. check_aruco_detection.py의
# "거리(m)" 추정은 카메라 캘리브레이션 없어서 pixel_size의 근사 역산일 뿐이라 안 씀.
ARUCO_ARRIVAL_MIN_PIXEL_SIZE = 24.6  # 실측 확인된 "확실히 잡힘" 기준(냉동구역 마커 id=0,
                                     # aruco_recognition_distance_tests.jsonl, 직선거리 약 68cm)
# 2026-08-13 갱신: 처음엔 pixel_size + AMCL거리(robot_x/y) 이중 게이트였으나, 사용자 판단으로
# AMCL거리 게이트를 빼고 pixel_size + 연속 프레임 게이트로 변경함 -- 마커는 멀리서도 보이기
# 시작하는 신호라서 "트리거 시점에 이미 가까워야 한다"는 AMCL거리 조건이 오히려 어색했음.
# 마커가 "확실히 잡히는" 위치(아래 68cm 실측)와 sub_sub_midgoal_N 저장 좌표(로봇팔 적재용
# 정차 지점)는 물리적으로 다른 점이어도 됨 -- 마커는 "이 근처가 맞다"는 확인 신호일 뿐,
# 실제 정차 위치/yaw는 sub_sub_midgoal_N이 NavigateToPose로 그대로 담당함.
ARUCO_ARRIVAL_MIN_CONSECUTIVE_FRAMES = 5  # orchestrate_live_teleop.py의 ObjectWatcher.
                                          # CONFIRM_FRAMES(3)보다 보수적으로 잡음(사용자
                                          # 판단, 5~7 범위 중 하단). 프레임 카운팅 자체는
                                          # 호출부(카메라 폴링 루프) 책임, 여기선 넘겨받은
                                          # 값을 기준치와 비교만 함.


class Stage(Enum):
    START = auto()
    LOADING = auto()       # 필요한 적재구역(들) 방문 중
    DELIVERING = auto()    # middle_goal로 이동 중
    END = auto()
    BATTERY_OVERRIDE = auto()


@dataclass
class FeaturePoint:
    id: str
    x: Optional[float] = None
    y: Optional[float] = None
    yaw: Optional[float] = None  # 방향이 의미 있는 지점만(적재구역/middle_goal/start_zone/end_zone).
    aruco_id: Optional[int] = None

    @property
    def ready(self) -> bool:
        return self.x is not None and self.y is not None


@dataclass
class BottleneckZone:
    """다중 로봇 상호배제 구역 -- FeaturePoint와 달리 목표 지점이 아니라 통과 제약 영역.
    Stage 흐름에 안 들어감, is_in_bottleneck()으로 순수 기하 판정만 제공."""
    id: str
    x: Optional[float] = None
    y: Optional[float] = None
    radius_m: Optional[float] = None

    @property
    def ready(self) -> bool:
        return self.x is not None and self.y is not None and self.radius_m is not None

    def contains(self, x: float, y: float) -> bool:
        if not self.ready:
            return False
        return (x - self.x) ** 2 + (y - self.y) ** 2 <= self.radius_m ** 2


def _load_points() -> tuple[
    FeaturePoint, dict[int, FeaturePoint], dict[int, FeaturePoint],
    dict[int, BottleneckZone], dict[int, FeaturePoint], dict[int, FeaturePoint],
]:
    """fms_feature_points.jsonl 파싱. 반환: (safe_zone, {번호:sub_sub_midgoal},
    {번호:middle_goal}, {번호:bottleneck}, {슬롯:start_zone}, {슬롯:end_zone}). 파일 없거나
    특정 label이 없으면 좌표 None인 placeholder로 채움(fail-closed 유지, 나중에 파일에
    추가되면 재로드만 하면 됨)."""
    safe_zone = FeaturePoint("safe_zone")
    sub_sub = {i: FeaturePoint(f"sub_sub_midgoal_{i}") for i in (1, 2, 3)}
    middle = {i: FeaturePoint(f"middle_goal_{i}") for i in (1, 2)}
    bottlenecks = {i: BottleneckZone(f"bottleneck_{i}") for i in (1, 2)}
    start_zones = {i: FeaturePoint(f"start_zone_{i}") for i in ZONE_SLOTS}
    end_zones = {i: FeaturePoint(f"end_zone_{i}") for i in ZONE_SLOTS}

    if not FMS_FEATURE_POINTS_PATH.exists():
        return safe_zone, sub_sub, middle, bottlenecks, start_zones, end_zones

    with FMS_FEATURE_POINTS_PATH.open() as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            label = e.get("label", "")
            if label == "safe_zone":
                safe_zone.x, safe_zone.y, safe_zone.yaw = e["map_x"], e["map_y"], e.get("map_yaw")
            elif label.startswith("sub_sub_midgoal_"):
                n = int(label.rsplit("_", 1)[-1])
                if n in sub_sub:
                    sub_sub[n].x, sub_sub[n].y = e["map_x"], e["map_y"]
                    sub_sub[n].yaw = e.get("map_yaw")
                    sub_sub[n].aruco_id = e.get("marker_id")
            elif label.startswith("middle_goal_"):
                n = int(label.rsplit("_", 1)[-1])
                if n in middle:
                    middle[n].x, middle[n].y = e["map_x"], e["map_y"]
                    middle[n].yaw = e.get("map_yaw")
            elif label.startswith("bottleneck_"):
                n = int(label.rsplit("_", 1)[-1])
                if n in bottlenecks:
                    bottlenecks[n].x, bottlenecks[n].y = e["map_x"], e["map_y"]
                    bottlenecks[n].radius_m = e.get("radius_m")
            elif label.startswith("start_zone_"):
                n = int(label.rsplit("_", 1)[-1])
                if n in start_zones:
                    start_zones[n].x, start_zones[n].y = e["map_x"], e["map_y"]
                    start_zones[n].yaw = e.get("map_yaw")
            elif label.startswith("end_zone_"):
                n = int(label.rsplit("_", 1)[-1])
                if n in end_zones:
                    end_zones[n].x, end_zones[n].y = e["map_x"], e["map_y"]
                    end_zones[n].yaw = e.get("map_yaw")
    return safe_zone, sub_sub, middle, bottlenecks, start_zones, end_zones


SAFE_ZONE, SUB_SUB_MIDGOALS, MIDDLE_GOALS, BOTTLENECKS, START_ZONES, END_ZONES = _load_points()


class MissionGoalStateMachine:
    """세션(로봇 1회 임무)당 인스턴스 하나. zone_slot으로 어느 도킹 슬롯(start_zone_N/end_zone_N)을
    쓰는지 지정 -- 로봇/자리별로 보통 고정될 값이라 생성 시점에 넘겨받음."""

    def __init__(self, loading_targets: list[int] | None = None, zone_slot: int = 1) -> None:
        """loading_targets: 방문해야 할 적재구역 번호 리스트(예: 냉동만이면 [3]).
        None이면 아직 미지정(외부에서 set_loading_targets로 나중에 채워도 됨).
        zone_slot: 1 또는 2 (ZONE_SLOTS) -- 이 세션이 쓰는 start_zone/end_zone 페어."""
        if zone_slot not in ZONE_SLOTS:
            raise ValueError(f"zone_slot은 {ZONE_SLOTS} 중 하나여야 함: {zone_slot}")
        self.zone_slot = zone_slot
        self.stage = Stage.START
        self._loading_targets = list(loading_targets) if loading_targets else []
        self._loading_idx = 0
        self._middle_goal1_available = True
        self._middle_goal2_available = True
        # 2026-08-13: 배터리 override가 safe_zone(사람 확인 필요)으로 갔는지, start_zone(충전
        # 가능, 자동재개)으로 갔는지 기억해둠 -- current_target()이 battery_low=True로 정할
        # 때 세팅되고, set_loading_targets()의 게이트 판단에 씀.
        self._battery_override_requires_operator = True

    def set_loading_targets(self, targets: list[int]) -> None:
        if self.stage == Stage.BATTERY_OVERRIDE and self._battery_override_requires_operator:
            raise RuntimeError(
                "BATTERY_OVERRIDE(safe_zone) 상태에서는 미션을 새로 시작할 수 없음 -- "
                "operator_release()로 먼저 해제해야 함(§ 정정 이력 6번, RECOVERY_RETURN "
                "REQUIRE_OPERATOR 시맨틱). start_zone으로 override됐다면 이 체크는 통과됨"
                "(충전소라 자동재개 허용, § 정정 이력 7번).")
        self._loading_targets = list(targets)
        self._loading_idx = 0
        if self._loading_targets:
            self.stage = Stage.LOADING

    def confirm_arrival_by_aruco(
        self, aruco_id: int, pixel_size: float | None = None,
        consecutive_frames: int | None = None,
    ) -> bool:
        """check_aruco_detection.py 등에서 마커 인식될 때 호출 -- 지금 향하고 있는 적재구역의
        마커 ID와 일치하면 그 구역 방문 완료 처리하고 다음 타겟으로 진행. 다른 구역 마커가
        찍히면(오검출/스쳐지나감 등) 무시. 반환값: 이번 감지로 실제 진행이 일어났는지.

        **이 함수가 "도착"으로 처리해도 로봇이 그 자리에 실제로 서있는 게 아님** -- 마커는
        "이 근처가 맞다"는 확인 신호일 뿐이고, 실제 정차 위치/yaw는 sub_sub_midgoal_N 저장
        좌표(NavigateToPose 목표)가 담당함(2026-08-13 사용자 확인, 두 지점이 물리적으로
        같을 필요 없음). 실제 사용 흐름: 마커가 연속 프레임 이상 안정적으로 보이면 그때
        sub_sub_midgoal_N을 NavigateToPose 목표로 잡아 정밀 접근 -> 도착 후 이 함수로 최종
        확인.

        2중 게이트(둘 다 선택적, 하위호환으로 인자 없이 id만으로도 동작). 처음엔 AMCL거리
        게이트도 있었으나 뺌(2026-08-13, 위 상수 주석 참고 -- 마커는 멀리서부터 보이는 신호라
        트리거 시점에 "이미 가까워야 한다"는 조건이 어색했음):
        - pixel_size(카메라 신호): 너무 멀리서 스친 건 아닌지
        - consecutive_frames(카메라 신호, 노이즈 필터): 1~2프레임 우연히 스친 오검출 배제 --
          카운팅 자체는 호출부(카메라 폴링 루프) 책임, orchestrate_live_teleop.py의
          ObjectWatcher.CONFIRM_FRAMES와 같은 패턴."""
        if self.stage != Stage.LOADING or self._loading_idx >= len(self._loading_targets):
            return False
        cur_n = self._loading_targets[self._loading_idx]
        cur_fp = SUB_SUB_MIDGOALS.get(cur_n)
        if cur_fp is None or cur_fp.aruco_id != aruco_id:
            return False
        if pixel_size is not None and pixel_size < ARUCO_ARRIVAL_MIN_PIXEL_SIZE:
            return False  # 카메라 기준 아직 멀음 -- 스쳐 지나간 것으로 판단
        if consecutive_frames is not None and consecutive_frames < ARUCO_ARRIVAL_MIN_CONSECUTIVE_FRAMES:
            return False  # 아직 몇 프레임 안 잡힘 -- 노이즈일 수 있음
        self._loading_idx += 1
        if self._loading_idx >= len(self._loading_targets):
            self.stage = Stage.DELIVERING
        return True

    def set_middle_goal1_available(self, available: bool) -> None:
        """middle goal1 우선, 없으면(적재 완료 등으로 불가하면) goal2 -- 외부(FMS/재고 시스템)
        에서 판단해서 알려주는 값."""
        self._middle_goal1_available = available

    def set_middle_goal2_available(self, available: bool) -> None:
        """2026-08-13 추가 -- middle_goal1이 처음엔 boolean 하나로만 판단해서 "1번 안 되면
        무조건 2번"이었는데, 2번마저 막혀있는 경우(다른 로봇이 인계 중 등)를 전혀 반영 못
        하는 문제가 있었음. 이제 둘 다 안 되면 _resolve_middle_goal_target()이 그 자리에서
        대기시킴."""
        self._middle_goal2_available = available

    def _resolve_middle_goal_target(self, robot_x: float, robot_y: float) -> FeaturePoint:
        """1번 우선, 안 되면 2번, **둘 다 안 되면 그 자리에서 대기**(2026-08-13 사용자 결정 --
        end_zone처럼 별도 대기 지점 만들 필요 없이 단순 정지로 충분하다고 판단). 대기용
        FeaturePoint는 로봇의 현재 위치를 그대로 목표로 돌려줌(=사실상 제자리, 호출부가
        NavigateToPose를 보내도 이동 없이 즉시 도착 처리됨)."""
        if self._middle_goal1_available:
            return MIDDLE_GOALS[1]
        if self._middle_goal2_available:
            return MIDDLE_GOALS[2]
        return FeaturePoint("middle_goal_wait_in_place", x=robot_x, y=robot_y)

    def mark_delivery_done(self) -> None:
        self.stage = Stage.END

    def operator_release(self, resume_stage: Stage = Stage.START) -> None:
        """2026-08-13 추가: 공식 Trihouse RMF waypoint 스펙(docs/guideline/waypoint.md)의
        `RECOVERY_RETURN_<NN>`(REQUIRE_OPERATOR 플래그)이 우리 safe_zone과 개념적으로 같다는
        걸 확인하고 반영함 -- safe_zone은 배터리 위급 override 도착지이자 "비상 해제 후 점검
        복귀 지점"이기도 함. 즉 로봇이 safe_zone에 도착했다고 자동으로 미션을 재개하면 안 되고,
        **사람이 명시적으로 이 메서드를 호출해야만** BATTERY_OVERRIDE에서 빠져나갈 수 있음
        (set_loading_targets가 BATTERY_OVERRIDE 상태에서 직접 호출되는 걸 막아둠).
        resume_stage 기본값 START -- 중단된 지점부터 이어가지 않고 처음부터 다시 시작하는 게
        안전하다고 판단(비상상황 원인 파악 전에 하던 작업을 그대로 재개하는 게 더 위험)."""
        if self.stage != Stage.BATTERY_OVERRIDE:
            raise RuntimeError(
                f"BATTERY_OVERRIDE 상태가 아님(현재 {self.stage}) -- 해제할 게 없음.")
        self.stage = resume_stage

    def start_new_mission_from_end(self, loading_targets: list[int]) -> float:
        """end_zone에 복귀해있던 로봇이 새 미션을 받을 때 호출. Stage를 LOADING으로 바꾸고,
        **출발 전 로봇이 회전해야 할 목표 yaw**(같은 슬롯 start_zone의 yaw)를 반환함 -- 실제
        후진/회전 실행(nav_recovery_executor의 backup/spin 액션 호출)은 호출부 책임, 이
        상태머신은 목표값만 제공(§ 모듈 docstring 정정 이력 5번 로직: 후진 -> 회전 -> 그 자리에서
        바로 출발, start_zone 좌표로 이동하는 스텝은 없음)."""
        self.set_loading_targets(loading_targets)
        start_fp = START_ZONES[self.zone_slot]
        if start_fp.yaw is None:
            raise RuntimeError(
                f"'{start_fp.id}' yaw 미확정 -- fms_feature_points.jsonl 확인 필요.")
        return start_fp.yaw

    def _resolve_end_target(self, occupied_end_slots: set[int] | None) -> FeaturePoint:
        """2026-08-13 추가: end_zone 슬롯 1 우선 -> 차있으면 2 -> 둘 다 차있으면 safe_zone에
        임시 정차. `occupied_end_slots`는 "지금 어느 슬롯에 다른 로봇이 있는지"를 나타내는
        DB/관제센터發 신호를 넣는 자리인데, **아직 그 신호 자체가 없음**(DB/Gateway API
        미구현, [[vlm_rl_db_schema_delivered]]) -- None이면 신호가 없다는 뜻이라 예전처럼
        이 세션 고정 슬롯(zone_slot)으로 그냥 감(하위호환, fail-safe). 나중에 실제 occupancy
        신호가 연결되면 여기에 그 값만 넣어주면 됨(호출부만 바뀌고 이 로직은 그대로).

        **주의: 이건 배터리 override(RECOVERY_RETURN)랑 완전히 다른 개념** -- 단순 혼잡으로
        인한 임시 대기라 `_battery_override_requires_operator`/`operator_release()`를 전혀
        안 건드림. safe_zone에 임시로 가있는 동안 슬롯이 비면 다음 `current_target()` 호출
        때 자동으로 그 슬롯으로 다시 안내됨(사람 개입 불필요)."""
        if occupied_end_slots is None:
            return END_ZONES[self.zone_slot]  # 신호 없음 -- 이 세션 고정 슬롯으로(하위호환)
        for slot in ZONE_SLOTS:  # (1, 2) 순서 -- 1번 우선
            if slot not in occupied_end_slots and END_ZONES[slot].ready:
                return END_ZONES[slot]
        return SAFE_ZONE  # 둘 다 차있음 -- 임시 정차

    def current_target(
        self, robot_x: float, robot_y: float, battery_low: bool = False,
        occupied_end_slots: set[int] | None = None,
    ) -> FeaturePoint:
        if battery_low:
            self.stage = Stage.BATTERY_OVERRIDE
            # 2026-08-13: safe_zone 고정이 아니라 로봇 위치 기준 더 가까운 충전 가능 지점으로
            # override. safe_zone은 지도상 냉동구역 쪽에 치우쳐있어서(y가 크게 음수), 상온/
            # 냉장구역 근처에서 배터리가 위급해지면 safe_zone까지 멀리 가야 하는 비효율이
            # 있었음 -- start_zone(같은 슬롯)도 충전 가능하다는 전제로 거리 비교해서 선택.
            # start_zone 좌표가 없으면(fail-safe) 기존처럼 무조건 safe_zone.
            start_fp = START_ZONES[self.zone_slot]
            if SAFE_ZONE.ready and start_fp.ready:
                d_safe = math.hypot(robot_x - SAFE_ZONE.x, robot_y - SAFE_ZONE.y)
                d_start = math.hypot(robot_x - start_fp.x, robot_y - start_fp.y)
                if d_start < d_safe:
                    self._battery_override_requires_operator = False  # 충전소 도착 -- 자동재개
                    return start_fp
            self._battery_override_requires_operator = True  # safe_zone=RECOVERY_RETURN -- 사람 확인 필요
            return SAFE_ZONE

        if self.stage == Stage.BATTERY_OVERRIDE:
            if not self._battery_override_requires_operator:
                return START_ZONES[self.zone_slot]
            return SAFE_ZONE
        if self.stage == Stage.START:
            return START_ZONES[self.zone_slot]
        if self.stage == Stage.END:
            return self._resolve_end_target(occupied_end_slots)
        if self.stage == Stage.LOADING:
            if self._loading_idx < len(self._loading_targets):
                n = self._loading_targets[self._loading_idx]
                return SUB_SUB_MIDGOALS.get(n, FeaturePoint(f"sub_sub_midgoal_{n}"))
            return self._resolve_end_target(occupied_end_slots)  # 방문 목록 비었으면 end_zone에서 대기
        # DELIVERING
        return self._resolve_middle_goal_target(robot_x, robot_y)

    def active_bottleneck(self, robot_x: float, robot_y: float) -> Optional[BottleneckZone]:
        """지금 위치가 어느 병목 mutex 구역 안인지 확인 -- Stage와 무관, 다중 로봇 조율 코드가
        매 사이클 호출해서 우선순위/정지 판단에 씀. 순수 기하 판정만 함, 실제 대기 여부는
        bottleneck_should_wait() 참고."""
        for bz in BOTTLENECKS.values():
            if bz.contains(robot_x, robot_y):
                return bz
        return None

    def bottleneck_should_wait(
        self, robot_x: float, robot_y: float, occupied_bottlenecks: set[int] | None = None,
        battery_critical: bool = False,
    ) -> Optional[BottleneckZone]:
        """지금 위치가 병목 안이고, 그 병목을 **다른 로봇이 이미 점유 중**이면 그
        BottleneckZone을 반환(=대기해야 함), 아니면 None.
        `occupied_bottlenecks`는 "지금 어느 병목번호가 다른 로봇에게 점유돼있는지"를 나타내는
        DB/관제센터發 신호 자리 -- end_zone 슬롯 배정(§ 정정 이력 8번)과 같은 이유로 아직
        그 신호 자체가 없음([[vlm_rl_db_schema_delivered]], ROS_DOMAIN_ID 분리로 로봇간
        직접 통신도 불가).

        **2026-08-13 기본값 확정**: `occupied_bottlenecks`가 `None`(신호 없음)이면 **보수적으로
        대기**(사용자 결정 -- 병목은 end_zone 슬롯과 달리 실제 충돌 위험 구간이라 신호 연결
        전까진 안전하게 막아둠). **단, `battery_critical=True`(배터리 CRITICAL_BATTERY_THRESHOLD
        이하)면 병목 우선권을 점유하고 무조건 통과시킴** -- 탈출경로(safe_zone/start_zone
        override)가 병목 mutex보다 우선순위 높음, 배터리 위급 상황에 병목 앞에서 무한 대기하다
        방전되는 걸 막기 위함(§ 정정 이력 7번 배터리 override 로직과 연결해서 호출부가
        `battery_critical`을 넘겨줘야 함, 예: `battery_watcher.percentage <=
        CRITICAL_BATTERY_THRESHOLD`)."""
        bz = self.active_bottleneck(robot_x, robot_y)
        if bz is None:
            return None
        if battery_critical:
            return None  # 배터리 위급 -- 병목 우선권 점유, 무조건 통과
        if occupied_bottlenecks is None:
            return bz  # 신호 없음 -- 보수적으로 대기
        bz_n = int(bz.id.rsplit("_", 1)[-1])
        if bz_n in occupied_bottlenecks:
            return bz  # 다른 로봇이 점유 중 -- 대기해야 함
        return None

    def bottleneck_should_yield(
        self, robot_x: float, robot_y: float, critical_claims: set[int] | None = None,
    ) -> bool:
        """이미 병목 안에 있는 로봇용 -- bottleneck_should_wait()의 반대쪽 관점. 배터리
        위급 로봇이 지금 이 병목에 우선권을 요구 중이면(critical_claims에 이 병목번호가
        있으면) True 반환, 즉 **먼저 들어왔어도 즉시 벗어나야 함**(critical_claims는
        bottleneck_should_wait()의 battery_critical=True 판정과 같은 소스에서 나오는
        DB/관제센터發 신호, 아직 없음).

        **[미결정] 양쪽 다 CRITICAL이면(둘 다 같은 병목에 배터리 위급으로 우선권 요구)
        누가 이기는지는 아직 안 정함** -- 사용자 제안: 배터리 잔량이 더 낮은 쪽 우선(timestamp
        기준보다 안전 -- 실제 방전까지 남은 여유를 직접 반영하니까). 이 tie-break 로직은
        occupied_bottlenecks/critical_claims 신호 자체가 각 로봇 배터리 %까지 실어 날라야
        구현 가능해서, 신호 스키마 설계할 때(DB/Gateway 연동 시점) 같이 정할 것. 극단적
        엣지케이스(2대 동시운용+동시 CRITICAL+같은 병목)라 지금은 로직 미구현, 이 메모만
        남겨둠."""
        if critical_claims is None:
            return False
        bz = self.active_bottleneck(robot_x, robot_y)
        if bz is None:
            return False
        bz_n = int(bz.id.rsplit("_", 1)[-1])
        return bz_n in critical_claims

    def loading_zone_should_wait(
        self, target_n: int, occupied_loading_zones: set[int] | None = None,
        battery_critical: bool = False,
    ) -> bool:
        """같은 적재구역(sub_sub_midgoal_<target_n>)에 이미 다른 로봇이 있으면 True(=대기
        해야 함) -- 그 자리로 NavigateToPose 보내기 전에 호출부(mission_runner.py 등)가
        확인해야 함. 공식 스펙의 `FROZEN_SAFE_WAIT_<NN>`/`PACKING_SAFE_WAIT_<NN>`(적재구역
        주변 안전 대기점)과 같은 문제를 다루지만, 새 홀딩포인트 좌표를 따로 만들지 않고
        병목(bottleneck_should_wait)과 같은 신호/판정 패턴만 재사용함 -- 좁은 선반 슬롯에
        로봇 두 대가 동시에 들어가면 물리적으로 부딪히는 건 병목이랑 동일한 문제라서.

        `occupied_loading_zones`는 DB/관제센터發 신호(아직 없음, [[vlm_rl_db_schema_delivered]]).
        신호 없으면 **보수적으로 대기**(병목과 같은 이유 -- 실제 충돌 위험 구간).

        2026-08-13: `battery_critical=True`면 bottleneck_should_wait()와 똑같이 무조건
        통과(대기 안 함) -- 일관성을 위해 모든 대기 판정에 배터리 위급 예외를 넣기로 함(사용자
        결정). 참고로 `_resolve_end_target()`는 BATTERY_OVERRIDE 상태에선 애초에 안 거치는
        경로라(곧바로 safe_zone/start_zone으로 감) 이 예외가 따로 필요 없음."""
        if battery_critical:
            return False  # 배터리 위급 -- 우선권 점유, 대기 없이 통과
        if occupied_loading_zones is None:
            return True  # 신호 없음 -- 보수적으로 대기
        return target_n in occupied_loading_zones


# 기존 nominal_trajectory.py 호출부(real_reward.py, orchestrate_live_teleop.py)와
# 그대로 호환되는 인터페이스. 실제로 이 파일로 교체할 때는 import만 바꾸면 됨.
_default_fsm = MissionGoalStateMachine()


def next_nominal_waypoint(x: float, y: float) -> dict:
    """nominal_trajectory.py의 next_nominal_waypoint(x, y) -> {id, x, y}와 동일 인터페이스.
    **주의**: 좌표 미확정 지점은 예외 발생 -- 가짜 좌표로 진행하지 않음(fail-closed)."""
    fp = _default_fsm.current_target(x, y)
    if not fp.ready:
        raise RuntimeError(
            f"'{fp.id}' 좌표 미확정 -- fms_feature_points.jsonl에 아직 없음. "
            "그동안은 기존 nominal_trajectory.py를 계속 쓸 것.")
    return {"id": fp.id, "x": fp.x, "y": fp.y}


if __name__ == "__main__":
    print("로드된 지점 상태:")
    print(f"  safe_zone(배터리 override 전용): ready={SAFE_ZONE.ready} ({SAFE_ZONE.x}, {SAFE_ZONE.y})")
    for n, fp in START_ZONES.items():
        print(f"  start_zone_{n}: ready={fp.ready} ({fp.x}, {fp.y}) yaw={fp.yaw}")
    for n, fp in END_ZONES.items():
        print(f"  end_zone_{n}: ready={fp.ready} ({fp.x}, {fp.y}) yaw={fp.yaw}")
    for n, fp in SUB_SUB_MIDGOALS.items():
        print(f"  sub_sub_midgoal_{n}: ready={fp.ready} ({fp.x}, {fp.y}) aruco_id={fp.aruco_id}")
    for n, fp in MIDDLE_GOALS.items():
        print(f"  middle_goal_{n}: ready={fp.ready} ({fp.x}, {fp.y})")
    for n, bz in BOTTLENECKS.items():
        print(f"  bottleneck_{n}: ready={bz.ready} ({bz.x}, {bz.y}) r={bz.radius_m}")

    print("\n냉동구역(3)만 적재하는 시나리오 시뮬레이션 (zone_slot=1):")
    fsm = MissionGoalStateMachine(loading_targets=[3], zone_slot=1)
    print(f"  stage={fsm.stage}, target={fsm.current_target(0, 0).id}")
    fsm.stage = Stage.LOADING  # set_loading_targets가 이미 하지만 명시적으로 보여주기용
    target = fsm.current_target(0, 0)
    print(f"  LOADING 단계 target={target.id} (ready={target.ready})")
    if target.aruco_id is not None:
        advanced = fsm.confirm_arrival_by_aruco(target.aruco_id)
        print(f"  ArUco 확인 후 진행됨={advanced}, 새 stage={fsm.stage}")

    print("\nEnd에서 새 미션 받는 시나리오 (냉장구역만):")
    fsm2 = MissionGoalStateMachine(zone_slot=1)
    fsm2.stage = Stage.END
    departure_yaw = fsm2.start_new_mission_from_end(loading_targets=[2])
    print(f"  departure_yaw(start_zone_1 기준)={departure_yaw}, 새 stage={fsm2.stage}")

    print("\n배터리 위급 -> safe_zone(RECOVERY_RETURN) 도착 -> 사람이 해제하는 시나리오:")
    fsm3 = MissionGoalStateMachine(zone_slot=1)
    # sub_sub_midgoal_3(냉동, safe_zone 근처) 위치에서 배터리 위급 -> safe_zone이 더 가까움
    target = fsm3.current_target(SUB_SUB_MIDGOALS[3].x, SUB_SUB_MIDGOALS[3].y, battery_low=True)
    print(f"  냉동구역 근처에서 battery_low=True -> target={target.id}, "
          f"requires_operator={fsm3._battery_override_requires_operator}")
    try:
        fsm3.set_loading_targets([1])
        print("  !! 여기 도달하면 버그 -- operator_release 없이 미션 시작됐음")
    except RuntimeError as e:
        print(f"  기대한 대로 차단됨: {e}")
    fsm3.operator_release()
    print(f"  operator_release() 후 stage={fsm3.stage} (재개 가능)")

    print("\n배터리 위급 -> start_zone(더 가까움, 충전소) 도착 -> 자동재개 시나리오:")
    fsm4 = MissionGoalStateMachine(zone_slot=1)
    # start_zone_1 바로 근처에서 배터리 위급 -> start_zone이 압도적으로 더 가까움
    target = fsm4.current_target(0.1, 0.2, battery_low=True)
    print(f"  target={target.id}, requires_operator={fsm4._battery_override_requires_operator}")
    fsm4.set_loading_targets([2])  # operator_release 없이 바로 재개돼야 함
    print(f"  operator_release 없이도 재개됨, 새 stage={fsm4.stage}")

    print("\nend_zone 슬롯 배정 시나리오 (occupied_end_slots는 DB 신호 자리, 지금은 직접 흉내):")
    fsm5 = MissionGoalStateMachine(zone_slot=1)
    fsm5.stage = Stage.END
    t = fsm5.current_target(0, 0, occupied_end_slots=None)
    print(f"  신호 없음(None) -> {t.id} (이 세션 고정 슬롯으로 fallback)")
    t = fsm5.current_target(0, 0, occupied_end_slots=set())
    print(f"  둘 다 비어있음 -> {t.id} (1번 우선)")
    t = fsm5.current_target(0, 0, occupied_end_slots={1})
    print(f"  1번 차있음 -> {t.id} (2번으로)")
    t = fsm5.current_target(0, 0, occupied_end_slots={1, 2})
    print(f"  둘 다 차있음 -> {t.id} (safe_zone 임시 정차, operator 게이트 없음)")
