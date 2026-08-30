"""§6.1 "RL 후보"의 그룹 샘플링 버전 -- TGRPO(HighLevelPolicy)로 K개 skill 샘플링,
skill마다 SAC(LowLevelPolicy)로 M개 좌표 샘플링해서 최대 K*M개 후보를 만든다.

recovery_data_collector.py의 sample_action()(실행용 단일 샘플, K=1,M=1)과 다른 용도 --
이건 토너먼트(§8.1)에 넣을 여러 후보를 만드는 쪽. HighLevelPolicy.sample(state,k)와
LowLevelPolicy.sample()은 이미 TGRPO 학습(그룹 샘플링) 용도로 구현돼있던 걸 그대로 재사용함
(새 신경망 구조 필요 없음).

좌표 프레임 주의: LowLevelPolicy가 내놓는 coord는 tanh(COORD_SCALE=2.0)로 squash된
값이라 로봇 "현재 pose 기준 상대 오프셋"으로 해석함(§6.2 1안 "현재 pose 중심의 동적
Recovery Envelope로 제한"과 일치). 절대 map 좌표가 아니므로 사용할 때 robot_pose에 더해야 함.

2026-08-11 Recovery Envelope clamp 추가: 체크포인트가 거의 미학습이라 raw tanh 출력이
COORD_SCALE=2.0에 가까운 값(최대 ~2m)으로 튀는 경우가 잦았음. 실제 지도(final_map_06)가
2.15m x 2.65m밖에 안 되는 상황에서 라이브 검증 중 6C-Lite 기하학적 필터가 모든 후보를
100% fail시키는 걸로 확인됨(후보가 지도 밖/벽 너머를 가리킴). 방향은 유지하고 거리(dx,dy
유클리드 norm)만 ENVELOPE_RADIUS_M로 clamp -- dyaw는 거리가 아니라서 그대로 둠.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import torch

from tgrpo_sac_hierarchical_v2 import SKILL_NAMES

ENVELOPE_RADIUS_M = 0.25  # 2026-08-11: 0.4m -> 0.25m로 축소 (0.4m일 때 survivor율 1.3%로 너무 낮았음,
                          # 실주행 보며 계속 조정 예정)
YAW_CLAMP_RAD = math.pi / 3  # 2026-08-11 밤: dyaw는 거리가 아니라서 처음엔 clamp 안 걸었는데,
                             # 실제 실행에서 최대 204도(거의 반바퀴) 회전이 나오는 게 확인됨
                             # (체크포인트 미학습이라 raw 값이 COORD_SCALE=2.0rad 가까이 튐).
                             # 회복 동작이 그렇게 크게 돌 필요는 없다고 보고 ±60도로 제한.


def _clamp_offset(dx: float, dy: float, radius_m: float = ENVELOPE_RADIUS_M) -> tuple[float, float]:
    """(dx,dy) 방향은 유지하고 거리만 radius_m 이내로 줄임 (이미 radius_m 이내면 그대로)."""
    dist = math.hypot(dx, dy)
    if dist <= radius_m or dist == 0:
        return dx, dy
    scale = radius_m / dist
    return dx * scale, dy * scale


def _clamp_yaw(dyaw: float, limit_rad: float = YAW_CLAMP_RAD) -> float:
    """dyaw를 [-limit_rad, +limit_rad] 이내로 줄임 (부호/방향은 유지)."""
    return max(-limit_rad, min(limit_rad, dyaw))


@dataclass
class RLCandidate:
    skill: int
    skill_name: str
    offset: tuple[float, float, float]  # (dx, dy, dyaw) -- 로봇 현재 pose 기준 상대
    map_x: float  # robot_pose에 offset 적용한 절대 map 좌표
    map_y: float
    map_yaw: float
    skill_log_prob: float  # 참고/디버깅용


def sample_candidate_group(high_policy, low_policy, state, robot_pose: tuple[float, float, float],
                            k: int, m: int, device: str = "cuda") -> list[RLCandidate]:
    """state 하나에서 K개 skill x M개 좌표 = 최대 K*M개 후보 생성 (categorical 샘플이라
    같은 skill이 중복으로 뽑힐 수 있음 -- 그룹 샘플링에서 자연스러운 현상, 걸러내지 않음)."""
    rx, ry, ryaw = robot_pose
    state_t = state if torch.is_tensor(state) else torch.tensor(state, dtype=torch.float32)
    state_t = state_t.to(device)

    candidates: list[RLCandidate] = []
    with torch.no_grad():
        skills, skill_log_probs = high_policy.sample(state_t, k=k)
        for i in range(k):
            skill_id = int(skills[i].item())
            skill_batch = skills[i:i + 1].repeat(m)
            state_batch = state_t.unsqueeze(0).repeat(m, 1)
            coords, _ = low_policy.sample(state_batch, skill_batch)
            for j in range(m):
                dx, dy, dyaw = coords[j].cpu().numpy().tolist()
                dx, dy = _clamp_offset(dx, dy)
                dyaw = _clamp_yaw(dyaw)
                map_x = rx + dx * math.cos(ryaw) - dy * math.sin(ryaw)
                map_y = ry + dx * math.sin(ryaw) + dy * math.cos(ryaw)
                map_yaw = ryaw + dyaw
                candidates.append(RLCandidate(
                    skill=skill_id, skill_name=SKILL_NAMES[skill_id],
                    offset=(dx, dy, dyaw), map_x=map_x, map_y=map_y, map_yaw=map_yaw,
                    skill_log_prob=float(skill_log_probs[i].item()),
                ))
    return candidates


if __name__ == "__main__":
    import numpy as np
    from tgrpo_sac_hierarchical_v2 import HighLevelPolicy, LowLevelPolicy

    device = "cuda" if torch.cuda.is_available() else "cpu"
    high_policy = HighLevelPolicy().to(device)
    low_policy = LowLevelPolicy().to(device)
    # 체크포인트 없이 랜덤 초기화 가중치로도 배선 자체는 테스트 가능
    fake_state = np.array([1.03, -0.01, 1.15, 0.636, -0.223, 0.5, 0.5, 0.72, 0.3], dtype=np.float32)
    robot_pose = (1.03, -0.01, 1.15)

    cands = sample_candidate_group(high_policy, low_policy, fake_state, robot_pose, k=3, m=2, device=device)
    print(f"K=3, M=2 -> 후보 {len(cands)}개 (기대: 6개)")
    for c in cands:
        print(f"  skill={c.skill_name:16s} offset=({c.offset[0]:+.2f},{c.offset[1]:+.2f},{c.offset[2]:+.2f}) "
              f"map=({c.map_x:.2f},{c.map_y:.2f},{c.map_yaw:.2f})")
