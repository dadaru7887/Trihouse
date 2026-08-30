"""recovery_data_collector.py / recovery_system_node.py가 쌓은 buffer(recovery_buffer.pkl)를
실제로 불러와서 SAC(하위 정책)/TGRPO(상위 정책) 업데이트를 돌리는 오프라인 학습 스크립트.

이게 없으면 지금까지 만든 파이프라인은 "행동하고 기록만 하는" 상태였음 -- 이 스크립트가
실제로 정책을 gradient update 시키는 마지막 조각. 팀원 문서 §10 "운영 중에는 학습하지 않는다,
RTX 5080이 정지/docked 상태일 때 학습" 원칙과 일치 -- 로봇 운행 중이 아니라 이 스크립트를
따로 실행할 때만 학습.

SAC: buffer의 (state, skill, coord, reward, next_state, done)을 그대로 replay -- off-policy라
실행됐던 transition을 몇 번이고 재사용 가능.
TGRPO: buffer에 저장된 실제 state들을 "시작점"으로 재사용해서, 그 state에서 **현재(학습 중인)
정책**으로 여러 skill을 다시 샘플 -> 실제 env가 없으니 저장된 reward를 그 state 근방의
근사치로 사용(완전한 재시뮬레이션은 아님, 팀원 문서 §9.2의 이상적 형태보다 단순화된 버전 --
진짜 rollout 환경 붙기 전까지의 임시 근사).

실행: python3 offline_train_from_buffer.py [n_epochs]
"""

from __future__ import annotations

import sys

import numpy as np
import torch

from recovery_data_collector import PersistentRecoveryBuffer
from tgrpo_sac_hierarchical_v2 import (
    DEVICE, STATE_DIM, HighLevelPolicy, LowLevelPolicy, SACAgent, TwinQ, N_SKILLS,
)

CHECKPOINT_PATH = "./sim_recovery_policy_checkpoint.pt"
BATCH_SIZE = 4
N_EPOCHS = int(sys.argv[1]) if len(sys.argv) > 1 else 20


def build_sac_batch(transitions: list[dict], indices: np.ndarray) -> tuple:
    batch = [transitions[i] for i in indices]
    s = torch.tensor(np.array([t["state"] for t in batch]), dtype=torch.float32, device=DEVICE)
    z = torch.tensor([t["skill"] for t in batch], dtype=torch.float32, device=DEVICE)
    p = torch.tensor(np.array([t["coord"] for t in batch]), dtype=torch.float32, device=DEVICE)
    r = torch.tensor([t["reward"] for t in batch], dtype=torch.float32, device=DEVICE).unsqueeze(-1)
    s2 = torch.tensor(np.array([t["next_state"] for t in batch]), dtype=torch.float32, device=DEVICE)
    done = torch.tensor([float(t["done"]) for t in batch], dtype=torch.float32, device=DEVICE).unsqueeze(-1)
    return s, z, p, r, s2, done


def tgrpo_update_from_buffer(high_policy: HighLevelPolicy, high_opt: torch.optim.Optimizer,
                              transitions: list[dict], state: np.ndarray) -> dict:
    """실제 rollout 환경 없이, buffer에 저장된 실제 (skill, reward) 관측치를 그룹으로 재사용.
    같은 state 근방에서 어떤 skill이 실제로 더 나은 결과였는지를 group-relative advantage로 학습.
    한계: 팀원 문서 §9.2처럼 "현재 정책으로 새로 trajectory 생성"이 아니라 "과거에 실행됐던
    관측치 재사용" -- off-policy에 가까운 근사(진짜 rollout 환경 붙으면 §9.2 방식으로 교체 권장)."""
    state_t = torch.tensor(state, dtype=torch.float32, device=DEVICE)

    # buffer에서 skill별로 실제 관측된 reward들을 모음 (그룹 구성)
    by_skill: dict[int, list[float]] = {k: [] for k in range(N_SKILLS)}
    for t in transitions:
        by_skill[t["skill"]].append(t["reward"])

    skills_with_data = [k for k, v in by_skill.items() if len(v) > 0]
    if len(skills_with_data) < 2:
        return {}  # 그룹 비교하려면 최소 2개 skill 데이터 필요

    logits = high_policy(state_t.unsqueeze(0)).squeeze(0)
    dist = torch.distributions.Categorical(logits=logits)

    skill_ids = torch.tensor(skills_with_data, device=DEVICE)
    log_probs = dist.log_prob(skill_ids)
    rewards = torch.tensor([np.mean(by_skill[k]) for k in skills_with_data],
                            dtype=torch.float32, device=DEVICE)
    advantage = (rewards - rewards.mean()) / (rewards.std() + 1e-6)

    loss = -(advantage.detach() * log_probs).mean()
    high_opt.zero_grad(); loss.backward(); high_opt.step()
    return {"tgrpo_loss": loss.item(), "n_skills_with_data": len(skills_with_data)}


def main() -> None:
    buffer = PersistentRecoveryBuffer(save_path="./sim_recovery_buffer.pkl")
    if len(buffer) < BATCH_SIZE:
        print(f"buffer 크기({len(buffer)})가 BATCH_SIZE({BATCH_SIZE})보다 작음 -- 더 모아야 학습 가능")
        return

    high_policy = HighLevelPolicy().to(DEVICE)
    low_policy = LowLevelPolicy().to(DEVICE)
    q = TwinQ().to(DEVICE)
    q_target = TwinQ().to(DEVICE)
    q_target.load_state_dict(q.state_dict())

    import os
    if os.path.exists(CHECKPOINT_PATH):
        ckpt = torch.load(CHECKPOINT_PATH, map_location=DEVICE)
        high_policy.load_state_dict(ckpt["high_policy"])
        low_policy.load_state_dict(ckpt["low_policy"])
        q.load_state_dict(ckpt["q"])
        q_target.load_state_dict(ckpt["q_target"])
        print(f"기존 checkpoint 로드: {CHECKPOINT_PATH}")

    high_opt = torch.optim.Adam(high_policy.parameters(), lr=3e-4)
    agent = SACAgent(
        policy=low_policy, q=q, q_target=q_target,
        policy_opt=torch.optim.Adam(low_policy.parameters(), lr=3e-4),
        q_opt=torch.optim.Adam(q.parameters(), lr=3e-4),
        log_alpha=torch.zeros(1, requires_grad=True, device=DEVICE),
        alpha_opt=None, target_entropy=-3.0,
    )
    agent.alpha_opt = torch.optim.Adam([agent.log_alpha], lr=3e-4)

    print(f"buffer 크기: {len(buffer)}, {N_EPOCHS} epoch 학습 시작...")
    n = len(buffer.transitions)
    for epoch in range(N_EPOCHS):
        indices = np.random.permutation(n)
        sac_losses = []
        for start in range(0, n - BATCH_SIZE + 1, BATCH_SIZE):
            batch_idx = indices[start:start + BATCH_SIZE]
            batch = build_sac_batch(buffer.transitions, batch_idx)
            log = agent.update(batch)
            sac_losses.append(log["critic_loss"])

        random_state = buffer.transitions[np.random.randint(n)]["state"]
        tgrpo_log = tgrpo_update_from_buffer(high_policy, high_opt, buffer.transitions, random_state)

        if (epoch + 1) % 5 == 0:
            avg_critic_loss = np.mean(sac_losses) if sac_losses else float("nan")
            print(f"[epoch {epoch+1:3d}] avg_critic_loss={avg_critic_loss:.3f} tgrpo={tgrpo_log}")

    torch.save({
        "high_policy": high_policy.state_dict(), "low_policy": low_policy.state_dict(),
        "q": q.state_dict(), "q_target": q_target.state_dict(),
    }, CHECKPOINT_PATH)
    print(f"\n학습 완료, checkpoint 저장: {CHECKPOINT_PATH}")
    print("다음 실행 시(로봇이 더 buffer를 채운 뒤) 이 checkpoint에서 이어서 학습 가능.")
    print("recovery_system_node.py에서도 이 checkpoint를 로드해서 학습된 정책으로 행동하게 해야 함")
    print("(현재 recovery_system_node.py는 TODO로만 표시되어 있고 실제 로드 코드는 없음).")


if __name__ == "__main__":
    main()
