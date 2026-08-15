"""mission_goal_state_machine.py(원본, driving_fms/)를 감싸는 얇은 래퍼 -- 원본은 "다음
목표가 어디인지"만 판단하고 실행은 절대 안 한다는 원칙을 지켜온 파일이라 그 원칙을 안 깨려고
원본을 직접 수정하지 않음. 여기서는 narrow_1~5(좁은 구간) 태그 정보만 추가로 붙여줌.

**중요한 설계 결정(2026-08-15)**: 이 파일도 "판단"만 함 -- Nav2를 실제로 멈추고
narrow3_rule_based_docking.py를 실행하는 건 이 파일이 아니라 그걸 가져다 쓰는 실제 주행
코드(orchestrate 스크립트)의 책임. FMS ver2는 "이 목표로 가려면 좁은 구간을 지나야 하고,
그게 narrow_X다"라는 사실만 알려줌.

narrow_1/2/3은 적재구역(sub_sub_midgoal_1/2/3) 도착 직전과 자연스럽게 묶임(그 구역
자체가 좁은 코너라서). narrow_5(통로 경유)랑 start_zone_1 출발 특수처리는 반대로 "어느
목표로 가는가"가 아니라 "지금 어디를 지나가고 있는가"(로봇 위치 기준) 문제라서 FMS가
알 필요 없음 -- narrow3_rule_based_docking.py가 로봇 좌표만 보고 직접 판단함(오늘 대화에서
이미 그렇게 정리됨).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mission_goal_state_machine import (  # noqa: E402
    FeaturePoint, MissionGoalStateMachine, Stage,
)

# 적재구역(loading) 목표 id -> narrow zone 이름. 오늘 확정한 것: 상온=narrow_1,
# 냉장=narrow_2, 냉동=narrow_3(오늘 밤 씨름했던 그 코너). id는 원본의
# f"sub_sub_midgoal_{n}" 포맷 그대로 씀.
NARROW_ZONE_FOR_LOADING_TARGET: dict[str, str] = {
    "sub_sub_midgoal_1": "narrow_1",  # 상온
    "sub_sub_midgoal_2": "narrow_2",  # 냉장
    "sub_sub_midgoal_3": "narrow_3",  # 냉동
}


def current_target_v2(
    fsm: MissionGoalStateMachine, robot_x: float, robot_y: float,
    battery_low: bool = False, occupied_end_slots: set[int] | None = None,
) -> tuple[FeaturePoint, Optional[str]]:
    """원본 current_target()을 그대로 호출하고, 그 결과가 narrow zone과 연결된 목표면
    (target, narrow_zone_name) 튜플로, 아니면 (target, None)으로 반환.

    사용 예 (실제 주행 코드에서):
        target, narrow_zone = current_target_v2(fsm, x, y)
        if narrow_zone:
            # Nav2 goal 보내지 말고 narrow3_rule_based_docking.py의 해당 zone 함수 호출
            run_zone_sequence(node, buf, pub, narrow_zone)
        else:
            # 평소대로 Nav2 NavigateToPose(target.x, target.y, target.yaw)
            ...
    """
    target = fsm.current_target(robot_x, robot_y, battery_low, occupied_end_slots)
    narrow_zone = NARROW_ZONE_FOR_LOADING_TARGET.get(target.id)
    return target, narrow_zone


def is_departing_from_start_zone_1(fsm: MissionGoalStateMachine) -> bool:
    """narrow_4 회피용 -- Stage.START에서 zone_slot==1이면 True. 실제 주행 코드가
    미션 시작 시 이 값 보고 narrow3_rule_based_docking.py의 depart_from_start_zone_1()을
    먼저 실행할지 결정하는 용도(로봇 좌표까지 다시 확인하는 건 그 함수가 알아서 함)."""
    return fsm.stage == Stage.START and fsm.zone_slot == 1


if __name__ == "__main__":
    # 원본 안 건드리고 잘 감싸지는지 구조만 확인하는 스모크테스트.
    fsm = MissionGoalStateMachine(zone_slot=1)
    fsm.set_loading_targets([3])  # 냉동만
    print("departing from start_zone_1?", is_departing_from_start_zone_1(fsm))
    target, narrow_zone = current_target_v2(fsm, 0.0, 0.0)
    print(f"START stage target={target.id}, narrow_zone={narrow_zone} (narrow_zone은 None 기대, "
          f"START는 narrow_1/2/3 매핑 대상 아님)")
