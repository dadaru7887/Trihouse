"""다음 주 실제 주행 시 바로 buffer를 채울 수 있게 하는 수집 루프.

오늘 밤 만든 조각들을 전부 연결:
  vlm_trigger_node.py의 decide_trigger() -> 트리거 걸리면
  vlm_contract_to_rl_state.py의 call_vlm_contract() + vlm_json_to_state() -> state 생성
  tgrpo_sac_hierarchical_v2.py의 HighLevelPolicy/LowLevelPolicy -> action(skill, coord) 샘플
  -> 실행(현재는 실행부 stub, Nav2 연동 전) -> 결과 관찰 -> reward 계산
  -> ReplayBuffer에 (s, z, p, r, s', done) 저장

실제 로봇 없이도 구조 자체는 지금 검증 가능(dummy reward/outcome으로). 로봇 붙으면
_execute_and_observe()의 stub 부분만 실제 Nav2/Fleet Adapter 호출로 교체하면 됨
(팀원 문서 §3.2 recovery lease state machine, Phase 1 범위).

이 스크립트가 하는 일은 팀원 문서 Phase 1(deterministic recovery shell) +
Phase 2(VLM JSON contract) 경계까지 -- SAC/TGRPO 실제 gradient 업데이트는 오프라인으로
쌓인 buffer를 갖고 나중에 돌리는 걸 전제로 함(팀원 문서 §10 "운영 중에는 학습하지 않는다"
원칙과 일치).
"""

from __future__ import annotations

import json
import pickle
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import torch

# 오늘 밤 만든 모듈들 재사용
from tgrpo_sac_hierarchical_v2 import (
    DEVICE, HighLevelPolicy, LowLevelPolicy, N_SKILLS, SKILL_NAMES, STATE_DIM,
)

BUFFER_SAVE_PATH = "./recovery_buffer.pkl"
SAVE_EVERY_N_EPISODES = 5


@dataclass
class Transition:
    state: np.ndarray
    skill: int
    coord: np.ndarray
    reward: float
    next_state: np.ndarray
    done: bool
    meta: dict = field(default_factory=dict)  # trigger_reason, timestamp, vlm_raw 등 감사용


class PersistentRecoveryBuffer:
    """팀원 문서 §5.3 EpisodeStep과 대응 -- 실행된 transition만 저장(탈락 후보는 저장 안 함,
    §5.3 "최종 선택된 좌표만 EpisodeStep이 된다" 원칙). 디스크에 append로 계속 쌓임."""

    def __init__(self, save_path: str = BUFFER_SAVE_PATH):
        self.save_path = Path(save_path)
        # dataclass 객체가 아니라 plain dict의 list로 저장 -- pickle이 클래스 정의를
        # __main__ 기준으로 찾는 문제(어느 스크립트로 실행했는지에 따라 로드 실패)를
        # 원천적으로 피하기 위함. 나중에 별도 오프라인 학습 스크립트에서 import해서
        # 불러올 때도 항상 동작하게 하려는 목적(실제로 이 문제로 로드 실패하는 것 확인함).
        self.transitions: list[dict] = []
        if self.save_path.exists():
            with open(self.save_path, "rb") as f:
                self.transitions = pickle.load(f)
            print(f"기존 buffer 로드: {len(self.transitions)}개 transition")

    def add(self, t: Transition) -> None:
        self.transitions.append(asdict(t))

    def save(self) -> None:
        with open(self.save_path, "wb") as f:
            pickle.dump(self.transitions, f)
        print(f"buffer 저장: {len(self.transitions)}개 transition -> {self.save_path}")

    def __len__(self) -> int:
        return len(self.transitions)


def sample_action(high_policy: HighLevelPolicy, low_policy: LowLevelPolicy,
                   state: np.ndarray) -> tuple[int, np.ndarray]:
    """현재 정책으로 skill 1개 + 그 skill 조건 좌표 1개 샘플 (실행용, 학습용 group 샘플링과 다름)."""
    state_t = torch.tensor(state, dtype=torch.float32, device=DEVICE)
    with torch.no_grad():
        skill, _ = high_policy.sample(state_t, k=1)
        coord, _ = low_policy.sample(state_t.unsqueeze(0), skill.float())
    return int(skill.item()), coord.squeeze(0).cpu().numpy()


def compute_real_reward(pre_state: dict, post_state: dict, terminal_critical: bool) -> tuple[float, dict]:
    """팀원 문서 §9.3 수식을 실제 관측치 기반으로. 지금은 입력이 dummy/stub이라 실제 배포 시
    pre_state/post_state를 실제 odom/costmap/Safety 상태로 채워야 함."""
    if terminal_critical:
        return -100.0, {"terminal_critical": True}

    w = dict(w_progress=1.0, w_clearance=5.0, w_intervention=2.0, w_time=0.1, r_rejoin=10.0)
    progress = pre_state["dist_to_goal"] - post_state["dist_to_goal"]
    # 2026-08-11 밤: 기준거리 1.5m는 테스트방(final_map_06, 2.15x2.65m)에선 거의 항상
    # 걸리는 값이라 확인됨 -- 로봇이 진짜 안전하게(progress+, 실행 성공) 움직여도 clearance_cost가
    # 압도해서 reward가 계속 크게 마이너스로 나옴(실측 사례: progress=+0.29인데 reward=-8.0).
    # 0.5m도 넓다고 판단해서 0.3m로 재조정(로봇 footprint 0.12m + 여유). (2026-08-11 밤
    # 정정: 이 방이 실제 배포 환경 자체라 이 값이 곧 실제 운영 스케일 기준값임.)
    clearance_cost = max(0.0, 0.3 - post_state["dist_to_obstacle"]) ** 2
    intervention = post_state.get("intervention_level", 0.0)
    time_cost = post_state["elapsed_sec"]
    rejoin_bonus = w["r_rejoin"] if post_state.get("mission_rejoined", False) else 0.0

    total = (w["w_progress"] * progress - w["w_clearance"] * clearance_cost
             - w["w_intervention"] * intervention - w["w_time"] * time_cost + rejoin_bonus)
    return total, {"progress": progress, "clearance_cost": clearance_cost, "rejoin_bonus": rejoin_bonus}


def execute_and_observe_stub(skill: int, coord: np.ndarray, pre_state: dict) -> tuple[dict, bool]:
    """TODO(로봇 연결 시 교체): 실제로는 여기서
      1. Recovery Coordinator -> Fleet Adapter -> Nav2에 좌표 제출 (팀원 문서 §3.2 상태기계)
      2. waypoint 도착/취소/timeout까지 대기
      3. 실행 후 실제 odom/costmap으로 post_state 관측
      4. Safety Supervisor 개입 여부(intervention_level), 충돌 여부(terminal_critical) 확인
    지금은 dummy로 "약간 목표에 가까워짐" 정도로 흉내만 냄."""
    post_state = dict(pre_state)
    post_state["dist_to_goal"] = max(0.0, pre_state["dist_to_goal"] - np.random.uniform(0.0, 0.5))
    post_state["dist_to_obstacle"] = pre_state["dist_to_obstacle"] + np.random.uniform(-0.2, 0.2)
    post_state["elapsed_sec"] = 1.0
    post_state["intervention_level"] = 0.0
    post_state["mission_rejoined"] = post_state["dist_to_goal"] < 0.3
    terminal_critical = post_state["dist_to_obstacle"] < 0.3
    return post_state, terminal_critical


def collect_one_episode(high_policy: HighLevelPolicy, low_policy: LowLevelPolicy,
                         buffer: PersistentRecoveryBuffer, trigger_reason: str,
                         max_steps: int = 5) -> None:
    """트리거 발동 -> 완전정지(가정) -> 여기서부터 recovery episode 시작.
    팀원 문서 §3.2 상태기계의 REASONING~EXECUTING 구간에 해당."""
    print(f"\n=== Recovery episode 시작 (trigger: {trigger_reason}) ===")

    # TODO: 실제로는 VLM 호출(vlm_contract_to_rl_state.call_vlm_contract) + 실제 odom으로
    # state 구성. 지금은 구조 검증용 dummy state.
    state = np.random.uniform(-1, 1, STATE_DIM).astype(np.float32)
    pre_state = {"dist_to_goal": 5.0, "dist_to_obstacle": 1.0}

    for step in range(max_steps):
        skill, coord = sample_action(high_policy, low_policy, state)
        post_state, terminal_critical = execute_and_observe_stub(skill, coord, pre_state)
        reward, reward_terms = compute_real_reward(pre_state, post_state, terminal_critical)

        next_state = np.random.uniform(-1, 1, STATE_DIM).astype(np.float32)  # TODO: 실제 관측
        done = terminal_critical or post_state.get("mission_rejoined", False)

        transition = Transition(
            state=state, skill=skill, coord=coord, reward=reward, next_state=next_state,
            done=done, meta={"trigger_reason": trigger_reason, "step": step,
                              "skill_name": SKILL_NAMES[skill], "reward_terms": reward_terms,
                              "timestamp": time.time()},
        )
        buffer.add(transition)
        print(f"  step {step}: skill={SKILL_NAMES[skill]:16s} reward={reward:7.2f} "
              f"done={done} ({reward_terms})")

        state = next_state
        pre_state = post_state
        if done:
            break

    print(f"episode 종료, buffer 크기: {len(buffer)}")


def main() -> None:
    high_policy = HighLevelPolicy().to(DEVICE)
    low_policy = LowLevelPolicy().to(DEVICE)
    buffer = PersistentRecoveryBuffer()

    # 데모: 트리거가 3번 발동했다고 가정하고 3개 episode 수집
    for i, reason in enumerate(["stall_10.2s", "ultrasonic_close_0.35m", "tracking_speed_22.1px"]):
        collect_one_episode(high_policy, low_policy, buffer, trigger_reason=reason)
        if (i + 1) % SAVE_EVERY_N_EPISODES == 0:
            buffer.save()

    buffer.save()
    print(f"\n최종 buffer 크기: {len(buffer)} transitions")
    print("다음 단계: 이 buffer로 tgrpo_sac_hierarchical_v2.py의 SACAgent.update()/tgrpo_skill_update()")
    print("오프라인으로 돌리면 실제 학습 시작 가능 (팀원 문서 §10: 운영 중 학습 금지, docked window에서).")


if __name__ == "__main__":
    main()
