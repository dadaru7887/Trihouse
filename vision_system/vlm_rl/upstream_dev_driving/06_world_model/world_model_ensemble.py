"""학습된(neural) world-model 앙상블 -- 원 설계 문서 §8 "E개 world-model 앙상블이 각자 위험을
예측 -> Risk_UCB = 평균 + kappa*표준편차"를 구현한 것. **2026-08-15 작성, 아직 실제 buffer로
학습/실행해본 적 없음** -- 지금까지 buffer가 너무 작아서(수십 개) 시도조차 안 했던 부분.
이번에 데이터를 더 모으면 바로 쓸 수 있게 미리 짜둠.

설계 근거:
- 데이터가 적을수록(수백 개 이하) 큰 모델은 과적합만 함 -- MBPO/PETS류 model-based RL에서
  흔히 쓰는 "작은 MLP 여러 개 앙상블(probabilistic ensemble)" 패턴을 그대로 채택. 각 멤버는
  독립적으로 초기화+셔플된 데이터로 학습해서, 앙상블 분산 자체가 "이 state-action이 학습
  데이터에서 얼마나 낯선지"(epistemic uncertainty)를 근사함.
- 입력: state(9차원) + skill(one-hot 5개) + coord(3차원, dx/dy/dyaw) -- SAC/TGRPO가 실제로
  다루는 것과 동일한 표현을 그대로 재사용해서 나중에 조합하기 쉽게 함.
- 출력: next_state 예측(9차원) + reward 예측(1차원). classification이 아니라 회귀라 MSE loss.
- **주의**: 이건 §8의 "완전한 형태"는 아님 -- 원 설계는 world-model이 여러 step 앞까지
  rollout하는 걸 상정하는데, 여기선 1-step 예측만 함(데이터가 적을 땐 multi-step보다
  1-step이 훨씬 안정적으로 학습됨, 필요하면 학습된 1-step 모델을 반복 적용해서 n-step
  rollout으로 확장 가능 -- `geometric_6c_lite.py`의 n-step 구조와 같은 패턴).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "02_pipeline_core"))

import numpy as np
import torch
import torch.nn as nn

from tgrpo_sac_hierarchical_v2 import STATE_DIM, N_SKILLS, COORD_DIM, DEVICE


class MLPWorldModelMember(nn.Module):
    """앙상블의 멤버 하나 -- (state, skill_onehot, coord) -> (next_state_delta, reward)."""

    def __init__(self, state_dim: int = STATE_DIM, n_skills: int = N_SKILLS,
                 coord_dim: int = COORD_DIM, hidden: int = 64):
        super().__init__()
        in_dim = state_dim + n_skills + coord_dim
        self.body = nn.Sequential(
            nn.Linear(in_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
        )
        # next_state는 절대값이 아니라 delta(state로부터의 변화량)로 예측 -- 절대값보다
        # delta 예측이 회귀 문제로서 훨씬 쉬움(state가 대부분 비슷한 범위에서 조금만 바뀜),
        # SAC/PPO 계열 dynamics model에서 흔히 쓰는 관행.
        self.next_state_head = nn.Linear(hidden, state_dim)
        self.reward_head = nn.Linear(hidden, 1)

    def forward(self, state: torch.Tensor, skill_onehot: torch.Tensor,
                coord: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        x = torch.cat([state, skill_onehot, coord], dim=-1)
        h = self.body(x)
        next_state_delta = self.next_state_head(h)
        reward = self.reward_head(h)
        return next_state_delta, reward


class WorldModelEnsemble:
    """E개 멤버를 관리. predict()가 평균+표준편차를 같이 반환해서 Risk_UCB 계산에 바로 씀."""

    def __init__(self, n_members: int = 5, **member_kwargs):
        self.members = [MLPWorldModelMember(**member_kwargs).to(DEVICE) for _ in range(n_members)]
        self.n_members = n_members

    def predict(self, state: np.ndarray, skill: int, coord: np.ndarray
                ) -> dict:
        """단일 (state, skill, coord)에 대해 앙상블 전체의 예측을 모아서 반환.
        학습 안 된 초기 상태에서도 그냥 동작은 함(당연히 예측값은 의미 없음, 구조 확인용)."""
        state_t = torch.tensor(state, dtype=torch.float32, device=DEVICE).unsqueeze(0)
        skill_oh = torch.zeros(1, N_SKILLS, device=DEVICE)
        skill_oh[0, skill] = 1.0
        coord_t = torch.tensor(coord, dtype=torch.float32, device=DEVICE).unsqueeze(0)

        next_states, rewards = [], []
        with torch.no_grad():
            for m in self.members:
                m.eval()
                delta, r = m(state_t, skill_oh, coord_t)
                next_states.append((state_t + delta).squeeze(0).cpu().numpy())
                rewards.append(r.item())

        next_states = np.stack(next_states)  # (n_members, state_dim)
        rewards = np.array(rewards)          # (n_members,)
        return {
            "next_state_mean": next_states.mean(axis=0),
            "next_state_std": next_states.std(axis=0),
            "reward_mean": float(rewards.mean()),
            "reward_std": float(rewards.std()),
        }

    def risk_ucb(self, state: np.ndarray, skill: int, coord: np.ndarray,
                  kappa: float = 1.0) -> float:
        """§8 원 설계 그대로: Risk_UCB = 평균 + kappa*표준편차 (보수적 상한 -- reward가 아니라
        '위험'을 예측하는 거라 편차가 클수록, 즉 앙상블이 확신 없을수록 위험을 높게 잡음).
        여기선 reward를 그대로 risk의 음수 프록시로 씀(reward 낮을수록 위험) -- 필요하면
        별도 risk head를 추가해서 분리하는 게 더 정확할 수 있음(지금은 단순화)."""
        pred = self.predict(state, skill, coord)
        return -pred["reward_mean"] + kappa * pred["reward_std"]

    def save(self, path: str) -> None:
        torch.save({"members": [m.state_dict() for m in self.members],
                    "n_members": self.n_members}, path)

    def load(self, path: str) -> None:
        ckpt = torch.load(path, map_location=DEVICE)
        assert len(ckpt["members"]) == self.n_members, "저장된 앙상블 크기랑 안 맞음"
        for m, sd in zip(self.members, ckpt["members"]):
            m.load_state_dict(sd)


if __name__ == "__main__":
    # 구조만 확인하는 스모크테스트 -- 학습 안 된 랜덤 초기화 상태로 predict()가 안 죽고
    # 그럴듯한 shape을 내는지만 봄. 실제 학습은 train_world_model.py에서.
    ensemble = WorldModelEnsemble(n_members=5)
    fake_state = np.random.randn(STATE_DIM).astype(np.float32)
    fake_coord = np.random.randn(COORD_DIM).astype(np.float32)
    result = ensemble.predict(fake_state, skill=0, coord=fake_coord)
    print("predict() 결과:", {k: (v.shape if hasattr(v, "shape") else v) for k, v in result.items()})
    print("risk_ucb():", ensemble.risk_ucb(fake_state, skill=0, coord=fake_coord))
    print("-- 구조 확인 완료 (학습 안 된 랜덤 가중치라 값 자체는 의미 없음) --")
